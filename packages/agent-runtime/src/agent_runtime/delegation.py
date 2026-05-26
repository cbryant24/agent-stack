from __future__ import annotations

from typing import Any
from ulid import ULID

from agent_runtime.exceptions import BudgetExhaustedError, DelegationError
from agent_runtime.models import BudgetConsumption, BudgetEnvelope, DelegationResult
from agent_runtime.registry import get_agent


async def delegate(
    target: str,
    request: dict[str, Any],
    budget: BudgetEnvelope,
    parent_tracker: Any | None = None,
) -> DelegationResult:
    from opentelemetry import trace
    from agent_runtime.budget import BudgetTracker, get_current_tracker
    from agent_runtime.tracing.decorators import record_delegation

    if budget.max_depth <= 0:
        raise DelegationError(target, "max delegation depth reached")

    try:
        handler = get_agent(target)
    except DelegationError:
        raise

    child_budget = budget.derive_child()
    run_id = str(ULID())

    resolved_parent = parent_tracker or get_current_tracker()

    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span(
        f"delegation.{target}",
        kind=trace.SpanKind.CLIENT,
    ) as delegation_span:
        delegation_span.set_attribute("delegation.target", target)
        delegation_span.set_attribute("delegation.run_id", run_id)

        try:
            async with BudgetTracker(child_budget, agent_name=target, run_id=run_id) as child_tracker:
                result_payload = await handler(request, child_budget)
                child_consumption = child_tracker.consumption

            status = "completed"
            stop_reason = None
            error = None

        except BudgetExhaustedError as e:
            child_consumption = e.consumption
            status = "partial"
            stop_reason = f"budget_exhausted:{e.dimension}"
            error = None
            result_payload = None

        except Exception as e:
            child_consumption = BudgetConsumption()
            status = "failed"
            stop_reason = None
            error = str(e)
            result_payload = None

        delegation_span.set_attribute("delegation.status", status)
        delegation_span.set_attribute("delegation.cost_usd", child_consumption.cost_usd)
        record_delegation(target, status, child_consumption.cost_usd)

        if resolved_parent is not None:
            resolved_parent.add_delegation(child_consumption.cost_usd)

        return DelegationResult(
            run_id=run_id,
            target_agent=target,
            status=status,  # type: ignore[arg-type]
            result=result_payload,
            consumption=child_consumption,
            stop_reason=stop_reason,
            error=error,
        )
