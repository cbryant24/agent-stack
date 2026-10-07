"""The one tool that spends LLM money: write Suno prompts.

`curate` also records each prompt as a pending generation. That write is an event (a prompt was
produced), not an interpretation, so it is automatic; the description and the preview say so.
"""

from __future__ import annotations

from agent_runtime import BudgetEnvelope
from agent_shell.tools.registry import EffectClass, ToolResult, ToolSpec
from pydantic import BaseModel, Field

from music_curation.agent import curate as _curate
from music_curation.chat.state import ChatState
from music_curation.chat.tools._common import fail, ok
from music_curation.reads import render_result

# Per-call hard cap (the session's tool budget still charges the real cost). max_depth=2 lets
# the agent delegate to tutorial-research when its own memory is thin.
GENERATE_CAP = BudgetEnvelope(max_items=1, max_depth=2, max_cost_usd=0.60, max_wall_time_sec=300)
# What the gate assumes before the call.
GENERATE_ESTIMATE_USD = 0.10


class GenerateArgs(BaseModel):
    request: str = Field(description="What the track should be, in the director's words.")
    skip_question: bool = Field(default=False, description="Skip the agent's own check for one clarifying "
                                "question. Use when the director already answered it.")


def make_craft_tools(state: ChatState) -> list[ToolSpec]:
    async def generate_tool(a: GenerateArgs) -> ToolResult:
        result = await _curate(a.request, budget=GENERATE_CAP, skip_question=a.skip_question)
        data = {"generation_ids": result.generation_ids, "status": result.status, "cost_usd": result.cost_usd,
                "run_id": result.run_id, "titles": result.suggested_titles}
        for gid, title in zip(result.generation_ids, result.suggested_titles + [""] * len(result.generation_ids),
                              strict=False):
            state.seen[gid] = title
        if not result.prompts:
            return fail(f"No prompts were produced (status {result.status}; cost ${result.cost_usd:.4f}).", data=data)
        q = result.pending_question
        tail = ("\n\nThe agent raised a clarifying question (shown above). Put it to the director; the prompts "
                "were written anyway and can be regenerated with their answer.") if q and q.get("ask") else ""
        return ok(render_result(result) + tail, data=data)

    return [ToolSpec(
        name="generate", effect=EffectClass.LLM_SPEND, input_model=GenerateArgs, handler=generate_tool,
        preview=lambda a: (f"Write Suno prompts for: {a.request[:300]}\n"
                           f"An LLM call, capped at ${GENERATE_CAP.max_cost_usd:.2f}. It may consult tutorial-research. "
                           "Each prompt is saved as a pending generation automatically."),
        estimate_cost=lambda a: GENERATE_ESTIMATE_USD,
        description="Write Suno prompts (style field, optional lyrics, titles, the theory behind them) for a request, "
                    "grounded in the director's taste lessons and prior reactions. Costs a few cents. Each prompt is "
                    "saved as a PENDING generation automatically; give the director the ids. Suno has no API: the "
                    "director runs the prompt by hand and reports back.",
    )]
