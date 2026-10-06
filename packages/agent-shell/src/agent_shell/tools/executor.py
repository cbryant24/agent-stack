from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from agent_runtime.tracing import span
from agent_shell.audit.log import AuditLog
from agent_shell.guard.gate import Gate
from agent_shell.proposals import write_draft
from agent_shell.tools.registry import ToolResult, ToolSpec


class Executor:
    """validate -> gate -> dry-run -> call -> ToolResult -> audit.

    Every call goes through here, whichever front end or engine made it.
    """

    def __init__(
        self,
        gate: Gate,
        audit: AuditLog,
        drafts_dir: Path,
        *,
        provider: Callable[[], str] = lambda: "unknown",
        model: Callable[[], str] = lambda: "unknown",
        dry_run: Callable[[], bool] = lambda: False,
    ) -> None:
        self.gate = gate
        self.audit = audit
        self.drafts_dir = drafts_dir
        self._provider, self._model, self._dry_run = provider, model, dry_run

    def bind(self, spec: ToolSpec) -> ToolSpec:
        """A copy of `spec` whose handler runs through this executor (for engines)."""

        async def handler(args: BaseModel | dict[str, Any]) -> ToolResult:
            raw = args.model_dump() if isinstance(args, BaseModel) else args
            return await self.run(spec, raw)

        return spec.model_copy(update={"handler": handler})

    async def run(self, spec: ToolSpec, raw_args: dict[str, Any]) -> ToolResult:
        with span(f"shell.tool.{spec.name}"):
            args, result, decision, cost = await self._run(spec, raw_args)
        self.audit.record(
            tool=spec.name, effect=spec.effect.value, args=args, decision=decision,
            dry_run=self._dry_run(), is_error=result.is_error, summary=result.text[:300],
            cost_usd=cost, provider=self._provider(), model=self._model(),
        )
        return result

    async def _run(
        self, spec: ToolSpec, raw: dict[str, Any]
    ) -> tuple[dict[str, Any], ToolResult, str, float]:
        try:
            parsed = spec.input_model.model_validate(raw)
        except ValidationError as e:
            return raw, _error(e), "invalid", 0.0

        args = parsed.model_dump()
        preview = _call(spec.preview, parsed)
        est = float(_call(spec.estimate_cost, parsed) or 0.0)
        outcome = await self.gate.decide(
            spec, args, preview=preview, est_cost=est, dry_run=self._dry_run()
        )

        if outcome.action == "dry_run":
            text = f"[dry-run] would run {spec.name}" + (f": {preview}" if preview else "")
            return args, ToolResult(text=text, data={"dry_run": True}), "dry_run", 0.0
        if outcome.action == "reject":
            return args, ToolResult(
                text="Declined by the user; nothing was run.", data={"rejected": True}
            ), "reject", 0.0
        if outcome.action == "defer":
            path = write_draft(self.drafts_dir, f"tool:{spec.name}", args)
            return args, ToolResult(
                text=f"Deferred to {path.name}; nothing was run.",
                data={"deferred": True}, artifacts=[str(path)],
            ), "defer", 0.0

        if outcome.args != args:  # edited: re-validate before running
            try:
                parsed = spec.input_model.model_validate(outcome.args)
            except ValidationError as e:
                return outcome.args, _error(e), "edit_invalid", 0.0
            args = parsed.model_dump()

        try:
            result = await spec.handler(parsed)
        except Exception as e:  # noqa: BLE001 - handler errors become results
            return args, _error(e), "error", 0.0

        cost = float(result.data.get("cost_usd", 0.0) or 0.0)
        budget = self.gate.budgets.for_effect(spec.effect)
        if budget is not None:
            budget.charge(cost)
        decision = "edit" if outcome.reason == "edited" else "allow"
        return args, result, decision, cost


def _call(fn: Callable[..., Any] | None, arg: BaseModel) -> Any:
    return fn(arg) if fn else None


def _error(e: Exception) -> ToolResult:
    text = f"{type(e).__name__}: {e}"
    return ToolResult(text=text, is_error=True, data={"error_type": type(e).__name__})

