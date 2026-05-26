from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field
from ulid import ULID


class BudgetMode(str, Enum):
    CONSERVATIVE = "conservative"
    NORMAL = "normal"
    EXPLORATORY = "exploratory"


class BudgetEnvelope(BaseModel):
    session_id: str = Field(default_factory=lambda: str(ULID()))
    parent_run_id: str | None = None
    max_items: int | None = None
    max_depth: int = 0
    max_cost_usd: float | None = None
    max_wall_time_sec: int | None = None
    mode: BudgetMode = BudgetMode.NORMAL
    notify_above_usd: float | None = None

    def derive_child(self, **overrides: Any) -> BudgetEnvelope:
        child_data: dict[str, Any] = {
            "session_id": self.session_id,
            "parent_run_id": self.session_id,
            "max_depth": self.max_depth - 1,
            "mode": self.mode,
            "notify_above_usd": self.notify_above_usd,
        }

        # Cap numeric limits: child cannot exceed parent
        for field in ("max_items", "max_cost_usd", "max_wall_time_sec"):
            parent_val = getattr(self, field)
            override_val = overrides.get(field)
            if parent_val is None:
                child_data[field] = override_val
            elif override_val is None:
                child_data[field] = parent_val
            else:
                child_data[field] = min(parent_val, override_val)

        # Non-capped overrides
        for key, val in overrides.items():
            if key not in ("max_items", "max_cost_usd", "max_wall_time_sec"):
                child_data[key] = val

        return BudgetEnvelope(**child_data)


class BudgetRemaining(BaseModel):
    items: int | None
    cost_usd: float | None
    wall_time_sec: float | None
    exhausted: bool
    reason: str | None


class BudgetConsumption(BaseModel):
    items_processed: int = 0
    cost_usd: float = 0.0
    wall_time_sec: float = 0.0
    llm_calls: int = 0
    tool_calls: int = 0
    delegations: int = 0

    def remaining(self, envelope: BudgetEnvelope) -> BudgetRemaining:
        exhausted = False
        reason: str | None = None

        items_left: int | None = None
        if envelope.max_items is not None:
            items_left = envelope.max_items - self.items_processed
            if items_left <= 0:
                exhausted = True
                reason = "max_items"

        cost_left: float | None = None
        if envelope.max_cost_usd is not None:
            cost_left = envelope.max_cost_usd - self.cost_usd
            if cost_left <= 0 and not exhausted:
                exhausted = True
                reason = "max_cost_usd"

        time_left: float | None = None
        if envelope.max_wall_time_sec is not None:
            time_left = float(envelope.max_wall_time_sec) - self.wall_time_sec
            if time_left <= 0 and not exhausted:
                exhausted = True
                reason = "max_wall_time_sec"

        return BudgetRemaining(
            items=items_left,
            cost_usd=cost_left,
            wall_time_sec=time_left,
            exhausted=exhausted,
            reason=reason,
        )


class DelegationRequest(BaseModel):
    target_agent: str
    request_payload: dict[str, Any]
    budget: BudgetEnvelope


class DelegationResult(BaseModel):
    run_id: str
    target_agent: str
    status: Literal["completed", "partial", "failed"]
    result: dict[str, Any] | None = None
    consumption: BudgetConsumption
    stop_reason: str | None = None
    error: str | None = None


class TraceEvent(BaseModel):
    event_type: Literal[
        "llm_call", "tool_call", "delegation", "memory_query",
        "memory_write", "error", "info"
    ]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    span_id: str = Field(default_factory=lambda: str(ULID()))
    parent_span_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
