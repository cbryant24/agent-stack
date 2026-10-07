from __future__ import annotations

import asyncio
import json
import re
import signal
from collections.abc import Mapping
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from agent_shell.engine.base import (
    Engine,
    TextDelta,
    ToolCallFinished,
    ToolCallStarted,
    TurnCost,
    TurnEnd,
)
from agent_shell.guard.gate import ConfirmRequest, Decision, DecisionKind
from agent_shell.proposals import ProposalReport, walk_proposals
from agent_shell.repl.commands import COMMANDS, EngineFactory, ReplContext, handle_slash
from agent_shell.session.api import ConfirmRequested, Session

_KEYS: dict[str, DecisionKind] = {"y": "accept", "n": "reject", "e": "edit", "d": "defer"}
_LABEL = {"accept": "y=accept", "reject": "n=reject", "edit": "e=edit", "defer": "d=defer"}


def _bindings() -> KeyBindings:
    kb = KeyBindings()

    @kb.add("enter")
    def _submit(event: Any) -> None:
        event.current_buffer.validate_and_handle()

    @kb.add("escape", "enter")
    def _newline(event: Any) -> None:
        event.current_buffer.insert_text("\n")

    return kb


class PromptConfirmer:
    """Shows the confirm panel and reads y/n/e/d. Also used for end-of-session proposals."""

    def __init__(self, console: Console, prompt: PromptSession[str]) -> None:
        self.console, self.prompt = console, prompt

    async def ask(self, request: ConfirmRequest) -> Decision:
        body = Text(json.dumps(request.args, indent=2, default=str))
        if request.preview:
            body = Text(f"{request.preview}\n\n") + body
        if request.warning:
            body += Text(f"\n\nwarning: {request.warning}", style="bold red")
        self.console.print(Panel(
            body, title=Text(f"{request.tool} ({request.effect.value})"), border_style="yellow"
        ))
        choices = "  ".join(_LABEL[k] for k in request.allowed)
        while True:
            try:
                raw = (await self.prompt.prompt_async(f"{choices} > ", completer=None)).strip().lower()
            except (KeyboardInterrupt, EOFError):
                return Decision(kind="reject")
            kind = _KEYS.get(raw[:1]) if raw else None
            if kind is None or kind not in request.allowed:
                self.console.print(f"enter one of: {choices}")
                continue
            if kind != "edit":
                return Decision(kind=kind)
            try:
                edited = (await self.prompt.prompt_async("new args (JSON) > ", completer=None)).strip()
                payload = json.loads(edited)
                if not isinstance(payload, dict):
                    raise ValueError("expected a JSON object")
            except (ValueError, KeyboardInterrupt, EOFError) as e:
                self.console.print(f"not changed: {e}")
                continue
            return Decision(kind="edit", payload=payload)


class _Stream:
    """Streams assistant text as Markdown; paused around anything else that prints."""

    def __init__(self, console: Console) -> None:
        self.console, self.text = console, ""
        self._live: Live | None = None

    def add(self, delta: str) -> None:
        self.text += delta
        if self._live is None:
            self._live = Live(Markdown(self.text), console=self.console, refresh_per_second=8)
            self._live.start()
        else:
            self._live.update(Markdown(self.text))

    def pause(self) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None
        self.text = ""


class ShellApp:
    def __init__(
        self,
        session: Session,
        *,
        console: Console | None = None,
        prompt: PromptSession[str] | None = None,
        engines: Mapping[str, Engine] | None = None,
        engine_factory: EngineFactory | None = None,
    ) -> None:
        self.session = session
        self.console = console or Console()
        self.prompt = prompt or self._make_prompt()
        self.ctx = ReplContext(session, engines, engine_factory)
        self.prompter = PromptConfirmer(self.console, self.prompt)

    def _make_prompt(self) -> PromptSession[str]:
        hist_dir = self.session.settings.agent_data_dir / "shell-history"
        hist_dir.mkdir(parents=True, exist_ok=True)
        return PromptSession(
            history=FileHistory(str(hist_dir / self.session.config.agent_name)),
            completer=WordCompleter(COMMANDS, pattern=re.compile(r"/[\w-]*")),
            key_bindings=_bindings(),
            multiline=True,
        )

    async def run(self, resume_id: str | None = None) -> ProposalReport:
        s = self.session
        await s.start(resume_id)
        self.console.print(f"[bold]{s.config.agent_name}[/] · session {s.session_id} · /help for commands")
        if s.dry_run:
            self.console.print("[yellow]dry-run is on[/]")
        while True:
            try:
                line = (await self.prompt.prompt_async("> ")).strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                continue
            if line.startswith("/"):
                res = await handle_slash(line, self.ctx)
                if res.output:
                    self.console.print(res.output, markup=False, highlight=False)
                if res.exit:
                    break
                if res.resume_id:
                    await s.close()
                    await s.start(res.resume_id)
                continue
            await self._turn(line)
        return await self._finish()

    async def _turn(self, text: str) -> None:
        s, stream = self.session, _Stream(self.console)
        turn_cost, reason = 0.0, "complete"
        loop = asyncio.get_running_loop()
        try:
            loop.add_signal_handler(signal.SIGINT, lambda: asyncio.ensure_future(s.interrupt()))
        except (NotImplementedError, RuntimeError):
            pass  # not available off the main thread / on some platforms
        try:
            async for ev in s.send(text):
                if isinstance(ev, TextDelta):
                    stream.add(ev.text)
                elif isinstance(ev, ConfirmRequested):
                    stream.pause()
                    s.confirm(await self.prompter.ask(ev.request))
                elif isinstance(ev, ToolCallStarted):
                    stream.pause()
                    self.console.print(Text(f"→ {ev.name} {json.dumps(ev.args, default=str)[:100]}", style="dim"))
                elif isinstance(ev, ToolCallFinished):
                    mark, style = ("✗", "red") if ev.result.is_error else ("✓", "green")
                    self.console.print(Text(f"{mark} {ev.result.text[:200]}", style=style))
                elif isinstance(ev, TurnCost):
                    turn_cost += ev.cost_usd
                elif isinstance(ev, TurnEnd):
                    reason = ev.reason
        finally:
            stream.pause()
            try:
                loop.remove_signal_handler(signal.SIGINT)
            except (NotImplementedError, RuntimeError, ValueError):
                pass
        spent = s.budgets.repl.spent
        note = "" if reason == "complete" else f" · {reason}"
        self.console.print(Text(f"turn ${turn_cost:.4f} · session ${spent:.4f}{note}", style="dim"))

    async def _finish(self) -> ProposalReport:
        proposals = await self.session.close()
        if not proposals:
            return ProposalReport()
        self.console.print(f"\n[bold]{len(proposals)} proposed write(s) from this session[/]")
        report = await walk_proposals(
            proposals, self.prompter, self.session.settings.drafts_dir(self.session.config.agent_name)
        )
        for p in report.accepted:
            if p.tool:
                res = await self.session.apply_proposal(p)
                mark, style = ("✗", "red") if res.is_error else ("✓", "green")
                self.console.print(Text(f"{mark} {p.tool}: {res.text[:300]}", style=style))
        self.console.print(
            f"accepted {len(report.accepted)} · deferred {len(report.deferred)} · skipped {len(report.skipped)}"
        )
        return report


