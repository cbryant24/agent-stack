from __future__ import annotations

from agent_shell.tools.registry import EffectClass, ToolResult, ToolSpec

from visual_generation.chat.interpretation import InterpretationError, interpret, render_interpretation
from visual_generation.chat.schemas import InterpretationInput
from visual_generation.chat.state import ChatState
from visual_generation.chat.tools._common import fail, ok, project_note, resolver_for


def make_interpret_tools(state: ChatState) -> list[ToolSpec]:
    async def propose(a: InterpretationInput) -> ToolResult:
        resolver = await resolver_for(state)
        try:
            fi = interpret(a, resolver)
        except InterpretationError as e:
            return fail(str(e))
        return ok(render_interpretation(fi, resolver), data=fi.model_dump())

    return [ToolSpec(
        name="propose_interpretation", effect=EffectClass.NONE, input_model=InterpretationInput, handler=propose,
        description=(
            "Structure the director's feedback as a proposal. YOU read the feedback and pass observations "
            "(attempt label, score layer, category, attribution, claim, observed/inferred/unresolved status, "
            "evidence). Labels are resolved to generations; any that do not resolve become open questions. "
            "Identity, staging and set failures are conditioning problems unless you give evidence. "
            "Nothing is stored. " + project_note(state)
        ),
    )]
