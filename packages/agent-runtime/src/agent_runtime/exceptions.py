from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_runtime.models import BudgetConsumption, BudgetEnvelope


class AgentRuntimeError(Exception):
    pass


class ConfigurationError(AgentRuntimeError):
    pass


class BudgetExhaustedError(AgentRuntimeError):
    def __init__(
        self,
        dimension: str,
        envelope: BudgetEnvelope,
        consumption: BudgetConsumption,
    ) -> None:
        self.dimension = dimension
        self.envelope = envelope
        self.consumption = consumption
        super().__init__(
            f"Budget exhausted on dimension '{dimension}': "
            f"{consumption.model_dump()} vs envelope {envelope.model_dump()}"
        )


class DelegationError(AgentRuntimeError):
    def __init__(self, target_agent: str, reason: str) -> None:
        self.target_agent = target_agent
        self.reason = reason
        super().__init__(f"Delegation to '{target_agent}' failed: {reason}")
