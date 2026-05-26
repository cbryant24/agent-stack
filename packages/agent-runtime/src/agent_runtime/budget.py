from __future__ import annotations

import time
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from agent_runtime.exceptions import BudgetExhaustedError
from agent_runtime.models import BudgetConsumption, BudgetEnvelope, TraceEvent
from agent_runtime.tracing.decorators import record_llm_call

# Pricing table: USD per 1M tokens, sourced 2026-05-26 from Anthropic docs
_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-7":   {"input": 15.00, "output": 75.00},
    "claude-opus-4-6":   {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-6": {"input":  3.00, "output": 15.00},
    "claude-haiku-4-5":  {"input":  0.80, "output":  4.00},
}

_current_tracker: ContextVar[BudgetTracker | None] = ContextVar(
    "current_tracker", default=None
)


def get_current_tracker() -> BudgetTracker | None:
    return _current_tracker.get()


class BudgetTracker:
    def __init__(
        self,
        envelope: BudgetEnvelope,
        agent_name: str,
        run_id: str | None = None,
    ) -> None:
        self.envelope = envelope
        self.agent_name = agent_name
        from ulid import ULID
        self.run_id = run_id or str(ULID())
        self._consumption = BudgetConsumption()
        self._start_time: float = 0.0
        self._persister: Any = None
        self._span: Any = None
        self._token: Any = None

    async def __aenter__(self) -> BudgetTracker:
        from opentelemetry import trace
        from agent_runtime.tracing.persistence import TracePersister

        self._start_time = time.monotonic()
        self._persister = TracePersister(agent=self.agent_name, run_id=self.run_id)
        self._persister.__enter__()

        tracer = trace.get_tracer(__name__)
        self._span_ctx = tracer.start_as_current_span("agent.run")
        self._span = self._span_ctx.__enter__()
        self._span.set_attribute("agent.name", self.agent_name)
        self._span.set_attribute("budget.session_id", self.envelope.session_id)
        self._span.set_attribute("budget.max_depth", self.envelope.max_depth)

        self._token = _current_tracker.set(self)

        self._persister.record(TraceEvent(
            event_type="info",
            metadata={"event": "run_start", "agent": self.agent_name, "run_id": self.run_id},
        ))
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        elapsed = time.monotonic() - self._start_time
        self._consumption.wall_time_sec = elapsed

        status = "failed" if exc_type is not None else "completed"
        if exc_type is BudgetExhaustedError:
            status = "partial"

        self._persister.record(TraceEvent(
            event_type="info",
            metadata={
                "event": "run_end",
                "agent": self.agent_name,
                "run_id": self.run_id,
                "status": status,
                "summary": self._consumption.model_dump(),
                "envelope": self.envelope.model_dump(),
            },
        ))
        self._persister.__exit__(exc_type, exc_val, exc_tb)

        if self._span is not None:
            self._span.set_attribute("run.status", status)
            self._span.set_attribute("run.cost_usd", self._consumption.cost_usd)
            self._span_ctx.__exit__(exc_type, exc_val, exc_tb)

        if self._token is not None:
            _current_tracker.reset(self._token)

    def add_llm_cost(self, model: str, input_tokens: int, output_tokens: int) -> None:
        prices = _PRICING.get(model, {"input": 0.0, "output": 0.0})
        cost = (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000
        self._consumption.cost_usd += cost
        self._consumption.llm_calls += 1
        record_llm_call(model, input_tokens, output_tokens, cost)

    def add_tool_call(self) -> None:
        self._consumption.tool_calls += 1

    def add_item_processed(self) -> None:
        self._consumption.items_processed += 1

    def add_delegation(self, child_cost_usd: float = 0.0) -> None:
        self._consumption.delegations += 1
        self._consumption.cost_usd += child_cost_usd

    def check_budget(self) -> None:
        elapsed = time.monotonic() - self._start_time
        self._consumption.wall_time_sec = elapsed

        if (
            self.envelope.max_items is not None
            and self._consumption.items_processed >= self.envelope.max_items
        ):
            raise BudgetExhaustedError("max_items", self.envelope, self._consumption)

        if (
            self.envelope.max_cost_usd is not None
            and self._consumption.cost_usd >= self.envelope.max_cost_usd
        ):
            raise BudgetExhaustedError("max_cost_usd", self.envelope, self._consumption)

        if (
            self.envelope.max_wall_time_sec is not None
            and elapsed >= self.envelope.max_wall_time_sec
        ):
            raise BudgetExhaustedError("max_wall_time_sec", self.envelope, self._consumption)

    def check_can_afford(self, cost_usd: float) -> bool:
        if self.envelope.max_cost_usd is None:
            return True
        return (self._consumption.cost_usd + cost_usd) <= self.envelope.max_cost_usd

    @property
    def consumption(self) -> BudgetConsumption:
        elapsed = time.monotonic() - self._start_time
        return self._consumption.model_copy(update={"wall_time_sec": elapsed})

    @property
    def remaining(self):
        return self.consumption.remaining(self.envelope)
