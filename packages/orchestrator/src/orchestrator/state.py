from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class OrchestratorState(TypedDict):
    """MessagesState-style state extended with per-turn budget consumption signal.

    The BudgetTracker itself is NOT stored here — the checkpointer must serialize
    state, and nodes reach the active tracker via get_current_tracker(). Each turn
    re-seeds budget_exhausted=False on input (last-write-wins over the checkpointed
    value); messages still accumulate through the add_messages reducer.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    budget_exhausted: bool
