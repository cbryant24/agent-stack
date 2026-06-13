"""Orchestrator session entry points."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from langchain_core.messages import AIMessage, HumanMessage

from agent_runtime import BudgetConsumption, BudgetEnvelope, BudgetExhaustedError
from agent_runtime.budget import BudgetTracker
from agent_runtime.config import get_config

from orchestrator.constants import DEFAULT_BUDGET, MAX_RESPONSE_TOKENS, MODEL_ORCHESTRATOR
from orchestrator.graph import build_graph
from orchestrator.tools import all_tools

logger = logging.getLogger(__name__)


@dataclass
class TurnResult:
    response: str
    status: str  # "completed" | "partial"
    consumption: BudgetConsumption


def build_app(checkpointer, *, model=None):
    """Build the compiled graph. `model` is injectable for tests; production uses
    ChatAnthropic(MODEL_ORCHESTRATOR)."""
    if model is None:
        from langchain_anthropic import ChatAnthropic

        model = ChatAnthropic(
            model=MODEL_ORCHESTRATOR,
            api_key=get_config().orchestrator_anthropic_api_key or get_config().anthropic_api_key,
            max_tokens=MAX_RESPONSE_TOKENS,
        )
    return build_graph(model, all_tools(), checkpointer)


def _final_text(messages: list) -> str:
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) or getattr(msg, "type", None) == "ai":
            content = msg.content
            if isinstance(content, list):  # Anthropic content blocks
                return "".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in content
                ).strip()
            return str(content).strip()
    return ""


async def run_turn(
    graph,
    message: str,
    thread_id: str,
    *,
    budget: BudgetEnvelope | None = None,
) -> TurnResult:
    """Run one conversational turn through the graph on `thread_id`, governed by a
    per-turn BudgetTracker (the parent for any in-turn sub-agent delegation). The
    active tracker is exposed to all nodes/tools via the runtime contextvar."""
    effective_budget = budget or DEFAULT_BUDGET
    status = "completed"
    final_messages: list = []

    async with BudgetTracker(effective_budget, "orchestrator") as tracker:
        config = {"configurable": {"thread_id": thread_id}}
        try:
            result = await graph.ainvoke(
                {"messages": [HumanMessage(content=message)], "budget_exhausted": False},
                config,
            )
            final_messages = result.get("messages", [])
            if result.get("budget_exhausted"):
                status = "partial"
        except BudgetExhaustedError:
            status = "partial"
        consumption = tracker.consumption

    return TurnResult(response=_final_text(final_messages), status=status, consumption=consumption)
