from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel
from ulid import ULID

from agent_shell.audit.log import AuditLog
from agent_shell.config import ChatConfig, ShellSettings
from agent_shell.engine.base import (
    Engine,
    EngineEvent,
    SessionHandle,
    SessionRef,
    TextDelta,
    ToolCallFinished,
    TurnCost,
    TurnEnd,
)
from agent_shell.guard.gate import ConfirmRequest, Confirmer, Decision, Gate, SessionBudgets
from agent_shell.proposals import Proposal
from agent_shell.session.store import SessionStore
from agent_shell.tools.executor import Executor
from agent_shell.tools.registry import Registry


class ConfirmRequested(BaseModel):
    request: ConfirmRequest


SessionEvent = EngineEvent | ConfirmRequested
_DONE = object()


class QueueConfirmer:
    """Front-end-neutral confirmer: asks arrive as events, `answer` resolves them."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[Any] | None = None
        self._future: asyncio.Future[Decision] | None = None
        self._request: ConfirmRequest | None = None

    def attach(self, queue: asyncio.Queue[Any]) -> None:
        self._queue = queue

    @property
    def pending(self) -> ConfirmRequest | None:
        return self._request if self._future and not self._future.done() else None

    async def ask(self, request: ConfirmRequest) -> Decision:
        if self._queue is None:
            raise RuntimeError("no turn in progress")
        self._request = request
        self._future = asyncio.get_running_loop().create_future()
        await self._queue.put(ConfirmRequested(request=request))
        return await self._future

    def answer(self, decision: Decision) -> None:
        if self._future is None or self._future.done():
            raise RuntimeError("no confirmation pending")
        self._future.set_result(decision)

    def reject_pending(self) -> None:
        if self._future and not self._future.done():
            self._future.set_result(Decision(kind="reject"))


class Session:
    """One chat session. No terminal code: a REPL, a test, or a bot can drive it.

    Usage: `await start()`, then `async for ev in send(text)`; answer `ConfirmRequested`
    events with `confirm(...)`; `interrupt()` stops the turn; `await close()` returns the
    end-of-session proposals.
    """

    def __init__(
        self,
        config: ChatConfig,
        settings: ShellSettings,
        engine: Engine,
        *,
        confirmer: Confirmer | None = None,
        store: SessionStore | None = None,
    ) -> None:
        self.config = config
        self.settings = settings
        self.engine = engine
        self.store = store or SessionStore(settings.db_path)
        self._broker: QueueConfirmer | None = None
        if confirmer is None:
            self._broker = QueueConfirmer()
            confirmer = self._broker
        self.confirmer: Confirmer = confirmer
        self.budgets = SessionBudgets.from_envelope(
            config.default_budget, tool_usd=settings.tool_budget_usd, gpu_usd=settings.gpu_budget_usd
        )
        self.dry_run = settings.dry_run
        self.session_id = ""
        self.registry = Registry()
        self.audit: AuditLog | None = None
        self.executor: Executor | None = None
        self.handle: SessionHandle | None = None
        self._turn: asyncio.Task[None] | None = None
        self._interrupted = False

    # lifecycle -------------------------------------------------------------
    async def start(self, resume_id: str | None = None) -> None:
        if resume_id and not self.store.exists(resume_id):
            raise KeyError(f"unknown session: {resume_id}")
        self.session_id = resume_id or str(ULID())
        self.registry = Registry(self.config.tool_pack())
        self.audit = AuditLog.for_session(
            self.settings.agent_data_dir, self.config.agent_name, self.session_id
        )
        gate = Gate(self.confirmer, self.budgets)
        self.executor = Executor(
            gate, self.audit, self.settings.drafts_dir(self.config.agent_name),
            provider=lambda: self.engine.provider, model=lambda: self.engine.model,
            dry_run=lambda: self.dry_run,
        )
        self.store.create(self.session_id, self.config.agent_name, self.engine.provider, self.engine.model)
        ref = SessionRef(
            session_id=self.session_id,
            transcript=self.store.messages(self.session_id),
            native_handle=self.store.handle(self.session_id, self.engine.provider),
        )
        self.handle = await self.engine.start(
            self.config.system_prompt, [self.executor.bind(t) for t in self.registry], ref
        )

    async def close(self) -> list[Proposal]:
        if self.handle is None:
            return []
        await self.interrupt()
        if self.handle.native_handle:
            self.store.set_handle(self.session_id, self.engine.provider, self.handle.native_handle)
        self.store.touch(self.session_id, self.engine.provider, self.engine.model)
        await self.engine.close(self.handle)
        proposals: list[Proposal] = []
        if self.config.on_session_end:
            proposals = list(self.config.on_session_end(self.store.messages(self.session_id)))
        self.handle = None
        return proposals

    # turns -----------------------------------------------------------------
    async def send(self, text: str) -> AsyncIterator[SessionEvent]:
        if self.handle is None:
            raise RuntimeError("session not started")
        queue: asyncio.Queue[Any] = asyncio.Queue()
        if self._broker:
            self._broker.attach(queue)
        self._interrupted = False
        self._turn = asyncio.create_task(self._produce(text, queue))
        try:
            while (item := await queue.get()) is not _DONE:
                yield item
        finally:
            if self._turn and not self._turn.done():
                await self.interrupt()

    async def _produce(self, text: str, queue: asyncio.Queue[Any]) -> None:
        assert self.handle is not None
        self.store.add_message(self.session_id, "user", text)
        reply: list[str] = []
        try:
            if self.budgets.repl.exhausted:
                await queue.put(TurnEnd(reason="budget_exhausted", detail="repl budget spent"))
                return
            async for ev in self.engine.send(self.handle, text):
                await queue.put(ev)
                if isinstance(ev, TextDelta):
                    reply.append(ev.text)
                elif isinstance(ev, ToolCallFinished):
                    self.store.add_message(self.session_id, "tool", f"{ev.name}: {ev.result.text}")
                elif isinstance(ev, TurnCost):
                    self.budgets.repl.charge(ev.cost_usd)
                    if self.budgets.repl.exhausted:
                        await self.engine.interrupt(self.handle)
                        await queue.put(TurnEnd(reason="budget_exhausted", detail="repl budget spent"))
                        return
        except asyncio.CancelledError:
            await self.engine.interrupt(self.handle)
            await queue.put(TurnEnd(reason="interrupted"))
        except Exception as e:  # noqa: BLE001 - surface engine failures as a turn end
            await queue.put(TurnEnd(reason="error", detail=f"{type(e).__name__}: {e}"))
        finally:
            if reply:
                self.store.add_message(self.session_id, "assistant", "".join(reply).strip())
            if self.handle.native_handle:
                self.store.set_handle(self.session_id, self.engine.provider, self.handle.native_handle)
            await queue.put(_DONE)

    def confirm(self, decision: Decision) -> None:
        if self._broker is None:
            raise RuntimeError("session uses an injected confirmer")
        self._broker.answer(decision)

    @property
    def pending_confirmation(self) -> ConfirmRequest | None:
        return self._broker.pending if self._broker else None

    async def interrupt(self) -> None:
        if self._turn and not self._turn.done():
            self._interrupted = True
            if self._broker:
                self._broker.reject_pending()
            self._turn.cancel()
            try:
                await self._turn
            except asyncio.CancelledError:
                pass

    def transcript(self) -> list[dict[str, str]]:
        return self.store.messages(self.session_id)
