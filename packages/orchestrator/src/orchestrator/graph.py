"""The orchestrator's hand-rolled ReAct graph.

One `agent` node (Sonnet, all tools bound) + one `tools` node (wraps ToolNode for
mechanical execution), joined by a conditional edge. Hand-rolled — rather than the
prebuilt create_react_agent — specifically so the runtime hooks are explicit
insertion points: a per-turn BudgetEnvelope guard that runs BEFORE each tool
execution and short-circuits to a partial answer when exhausted, plus
record_tool_call per tool step.
"""
from __future__ import annotations

import logging

from langchain_core.messages import ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from agent_runtime.budget import get_current_tracker
from agent_runtime.exceptions import BudgetExhaustedError
from agent_runtime.tracing import record_tool_call
from agent_runtime.tracing.decorators import _safe_attr

from orchestrator.constants import MODEL_ORCHESTRATOR
from orchestrator.state import OrchestratorState

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are the Orchestrator: the conversational meta-agent for the agent-stack "
    "system. You know what every agent does, answer questions about the system, "
    "retrieve from its knowledge bases, read its live code and docs, and invoke the "
    "other agents as tools on the user's behalf.\n\n"
    "Use search_knowledge for semantic recall from the knowledge bases. Use read_file "
    "and grep to inspect live source and docs (this is how you answer questions about "
    "how an agent works or how to use it — read the code, do not guess). Use the "
    "tutorial-research and music-curation tools to delegate real work; prefer the "
    "cheap retrieve/recall variants before the budget-spending research/generate ones. "
    "If a tool reports a budget limit was reached, summarize what you have and stop."
)


def _last_ai_tool_calls(state: OrchestratorState):
    messages = state["messages"]
    if not messages:
        return None
    return getattr(messages[-1], "tool_calls", None)


def should_continue(state: OrchestratorState) -> str:
    """agent -> tools (if the last AI message has tool calls and budget remains),
    else END. Once budget_exhausted is set, always END after the agent's partial
    answer so the turn never runs another tool."""
    if state.get("budget_exhausted"):
        return END
    return "tools" if _last_ai_tool_calls(state) else END


def build_graph(model, tools: list, checkpointer):
    """Compile the ReAct StateGraph. `model` is injected (a ChatAnthropic in
    production, a stub in tests). `checkpointer` is a LangGraph saver."""
    model_with_tools = model.bind_tools(tools)
    tool_node = ToolNode(tools)

    async def agent_node(state: OrchestratorState) -> dict:
        messages = state["messages"]
        # Prepend the system prompt on the first turn only (it persists in the thread).
        if not messages or getattr(messages[0], "type", None) != "system":
            from langchain_core.messages import SystemMessage

            messages = [SystemMessage(content=SYSTEM_PROMPT), *messages]
        response = await model_with_tools.ainvoke(messages)

        tracker = get_current_tracker()
        usage = getattr(response, "usage_metadata", None)
        if tracker is not None and usage:
            tracker.add_llm_cost(
                MODEL_ORCHESTRATOR,
                usage.get("input_tokens", 0),
                usage.get("output_tokens", 0),
            )
        return {"messages": [response]}

    async def tools_node(state: OrchestratorState) -> dict:
        tracker = get_current_tracker()
        last_calls = _last_ai_tool_calls(state) or []

        # Budget guard BEFORE any tool runs — short-circuit to a partial answer.
        if tracker is not None:
            try:
                tracker.check_budget()
            except BudgetExhaustedError:
                skips = [
                    ToolMessage(
                        content="Skipped — per-turn budget exhausted before this tool ran.",
                        tool_call_id=tc["id"],
                    )
                    for tc in last_calls
                ]
                return {"messages": skips, "budget_exhausted": True}

        result = await tool_node.ainvoke(state)

        # Per executed tool step: record_tool_call (also bridges to add_tool_call,
        # keeping consumption.tool_calls accurate) and add_item_processed (enforces
        # max_items, the per-turn tool-call ceiling). Do NOT also call add_tool_call.
        produced = result.get("messages", []) if isinstance(result, dict) else []
        outputs_by_id = {getattr(m, "tool_call_id", None): m for m in produced}
        for tc in last_calls:
            out_msg = outputs_by_id.get(tc["id"])
            out_summary = str(getattr(out_msg, "content", "")) if out_msg is not None else ""
            record_tool_call(tc["name"], _safe_attr(tc.get("args", {})), out_summary)
            if tracker is not None:
                tracker.add_item_processed()
        return result

    builder = StateGraph(OrchestratorState)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", tools_node)
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    builder.add_edge("tools", "agent")
    return builder.compile(checkpointer=checkpointer)
