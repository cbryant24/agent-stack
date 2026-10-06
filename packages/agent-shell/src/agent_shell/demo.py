from __future__ import annotations

from pydantic import BaseModel

from agent_runtime.models import BudgetEnvelope
from agent_shell.config import ChatConfig
from agent_shell.engine.fake import Call, FakeEngine, Say
from agent_shell.proposals import Proposal
from agent_shell.tools.registry import EffectClass, ToolResult, ToolSpec


class LookupArgs(BaseModel):
    topic: str


class SaveLessonArgs(BaseModel):
    statement: str


class RenderArgs(BaseModel):
    prompt: str
    steps: int = 8


async def _lookup(a: LookupArgs) -> ToolResult:
    return ToolResult(text=f"found 3 notes on {a.topic!r}", data={"count": 3})


async def _save(a: SaveLessonArgs) -> ToolResult:
    return ToolResult(text=f"saved lesson: {a.statement}", data={"id": "lesson-1"})


async def _render(a: RenderArgs) -> ToolResult:
    return ToolResult(text=f"rendered {a.prompt!r} in {a.steps} steps", data={"cost_usd": 0.05},
                      artifacts=["/tmp/demo.png"])


def demo_tools() -> list[ToolSpec]:
    return [
        ToolSpec(name="lookup", description="read-only search (no gate)", input_model=LookupArgs,
                 effect=EffectClass.READ, handler=_lookup),
        ToolSpec(name="save_lesson", description="memory write: y/n/edit/defer",
                 input_model=SaveLessonArgs, effect=EffectClass.MEMORY_WRITE, handler=_save,
                 preview=lambda a: f"write lesson to memory: {a.statement}"),
        ToolSpec(name="render", description="GPU spend: always asks", input_model=RenderArgs,
                 effect=EffectClass.GPU_SPEND, handler=_render,
                 preview=lambda a: f"render {a.prompt!r}, {a.steps} steps, ~$0.05",
                 estimate_cost=lambda a: 0.05),
    ]


def _on_end(transcript: list[dict[str, str]]) -> list[Proposal]:
    n = sum(1 for m in transcript if m["role"] == "user")
    return [Proposal(kind="lesson", summary=f"Session had {n} turns; note that dry-run is useful.",
                     payload={"statement": "use /dry-run before spending"})]


def demo_config() -> ChatConfig:
    return ChatConfig(
        agent_name="demo", system_prompt="You are a demo agent.", tool_pack=demo_tools,
        default_budget=BudgetEnvelope(max_cost_usd=1.0), on_session_end=_on_end,
    )


def demo_engine() -> FakeEngine:
    return FakeEngine(
        [
            [Say(text="Let me look that up.", cost_usd=0.01), Call(name="lookup", args={"topic": "lighting"}),
             Say(text="Found notes. Try asking me to **save a lesson**.", cost_usd=0.01)],
            [Say(text="Saving that lesson (you will be asked).", cost_usd=0.01),
             Call(name="save_lesson", args={"statement": "warm key light reads as cozy"})],
            [Say(text="Rendering a preview (GPU: you will be asked).", cost_usd=0.01),
             Call(name="render", args={"prompt": "a lit room", "steps": 8})],
        ],
        delay=0.02,
    )
