from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel

from agent_runtime.models import BudgetEnvelope
from agent_shell.tools.registry import EffectClass, ToolSpec

DecisionKind = Literal["accept", "reject", "edit", "defer"]

# Effects that are confirmed or skipped under dry-run.
GATED = frozenset({
    EffectClass.LLM_SPEND,
    EffectClass.GPU_SPEND,
    EffectClass.MEMORY_WRITE,
    EffectClass.DESTRUCTIVE_LOCAL,
})
_YN: tuple[DecisionKind, ...] = ("accept", "reject")
_YNED: tuple[DecisionKind, ...] = ("accept", "reject", "edit", "defer")


class ConfirmRequest(BaseModel):
    tool: str
    effect: EffectClass
    args: dict[str, Any]
    preview: str | None = None
    allowed: tuple[DecisionKind, ...] = _YN
    warning: str | None = None


class Decision(BaseModel):
    kind: DecisionKind
    payload: dict[str, Any] | None = None   # replacement args for "edit"


class Confirmer(Protocol):
    async def ask(self, request: ConfirmRequest) -> Decision: ...


class Budget:
    """One USD budget. `max_usd=None` means unlimited."""

    def __init__(self, name: str, max_usd: float | None) -> None:
        self.name = name
        self.max_usd = max_usd
        self.spent = 0.0

    @property
    def remaining(self) -> float | None:
        return None if self.max_usd is None else self.max_usd - self.spent

    @property
    def exhausted(self) -> bool:
        return self.max_usd is not None and self.spent >= self.max_usd

    def can_afford(self, usd: float) -> bool:
        return self.max_usd is None or self.spent + usd <= self.max_usd

    def charge(self, usd: float) -> None:
        self.spent += max(usd, 0.0)


class SessionBudgets:
    """Three orthogonal budgets: REPL LLM, tool LLM (child envelope), GPU."""

    def __init__(self, repl: Budget, tool: Budget, gpu: Budget) -> None:
        self.repl, self.tool, self.gpu = repl, tool, gpu

    @classmethod
    def from_envelope(
        cls, envelope: BudgetEnvelope, *, tool_usd: float, gpu_usd: float
    ) -> SessionBudgets:
        child = envelope.derive_child(max_cost_usd=tool_usd)
        return cls(
            Budget("repl", envelope.max_cost_usd),
            Budget("tool", child.max_cost_usd),
            Budget("gpu", gpu_usd),
        )

    def for_effect(self, effect: EffectClass) -> Budget | None:
        if effect is EffectClass.LLM_SPEND:
            return self.tool
        if effect is EffectClass.GPU_SPEND:
            return self.gpu
        return None

    def summary(self) -> dict[str, dict[str, float | None]]:
        return {
            b.name: {"spent": round(b.spent, 6), "max": b.max_usd}
            for b in (self.repl, self.tool, self.gpu)
        }


class GateOutcome(BaseModel):
    action: Literal["allow", "reject", "defer", "dry_run"]
    args: dict[str, Any]
    reason: str = ""


class Gate:
    def __init__(self, confirmer: Confirmer, budgets: SessionBudgets) -> None:
        self.confirmer = confirmer
        self.budgets = budgets

    async def decide(
        self,
        spec: ToolSpec,
        args: dict[str, Any],
        *,
        preview: str | None,
        est_cost: float,
        dry_run: bool,
    ) -> GateOutcome:
        effect = spec.effect
        if effect not in GATED:
            return GateOutcome(action="allow", args=args)
        if dry_run:
            return GateOutcome(action="dry_run", args=args, reason="dry-run")

        warning: str | None = None
        budget = self.budgets.for_effect(effect)
        if effect is EffectClass.LLM_SPEND:
            if budget is None or budget.can_afford(est_cost):
                return GateOutcome(action="allow", args=args)
            warning = f"exceeds {budget.name} budget (remaining {budget.remaining})"
            allowed: tuple[DecisionKind, ...] = _YN
        elif effect is EffectClass.MEMORY_WRITE:
            allowed = _YNED
        else:
            allowed = _YN
            if effect is EffectClass.GPU_SPEND and budget and not budget.can_afford(est_cost):
                warning = f"exceeds {budget.name} budget (remaining {budget.remaining})"

        decision = await self.confirmer.ask(ConfirmRequest(
            tool=spec.name, effect=effect, args=args, preview=preview,
            allowed=allowed, warning=warning,
        ))
        if decision.kind not in allowed:
            return GateOutcome(action="reject", args=args, reason=f"{decision.kind} not allowed")
        if decision.kind == "accept":
            return GateOutcome(action="allow", args=args)
        if decision.kind == "edit":
            return GateOutcome(action="allow", args=decision.payload or args, reason="edited")
        if decision.kind == "defer":
            return GateOutcome(action="defer", args=args)
        return GateOutcome(action="reject", args=args)


class AutoConfirmer:
    """Scripted confirmer for tests and --yes runs."""

    def __init__(self, *answers: Decision | DecisionKind) -> None:
        self._answers = [Decision(kind=a) if isinstance(a, str) else a for a in answers]
        self.requests: list[ConfirmRequest] = []

    async def ask(self, request: ConfirmRequest) -> Decision:
        self.requests.append(request)
        return self._answers.pop(0) if self._answers else Decision(kind="reject")


__all__ = [
    "AutoConfirmer", "Budget", "ConfirmRequest", "Confirmer", "Decision", "Gate",
    "GateOutcome", "SessionBudgets",
]
