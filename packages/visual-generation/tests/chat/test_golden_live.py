"""Live check of propose_interpretation over real feedback strings (golden/feedback.jsonl).

Skipped unless AGENT_SHELL_LIVE=1 (it calls a real model, a few cents per string):

    op run --env-file=.env -- env AGENT_SHELL_LIVE=1 uv run pytest packages/visual-generation -m live -v

For each string a real engine must call propose_interpretation and get a valid result, and every
label that does not resolve must end up in open_questions.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from agent_runtime.models import BudgetEnvelope
from agent_shell.config import ChatConfig, ShellSettings
from agent_shell.engine.base import ToolCallFinished, TurnEnd
from agent_shell.engine.factory import make_engine
from agent_shell.session.api import Session
from agent_shell.testing import drain

from visual_generation.chat.config import system_prompt
from visual_generation.chat.labels import LabelResolver
from visual_generation.chat.schemas import FeedbackInterpretation
from visual_generation.chat.tools import tool_pack

from .conftest import Built, make_gens  # type: ignore[import-not-found]

pytestmark = [pytest.mark.live, pytest.mark.asyncio]

GOLDEN = Path(__file__).parent / "golden" / "feedback.jsonl"
CASES = [json.loads(x) for x in GOLDEN.read_text().splitlines() if x.strip() and not x.startswith("#")]


@pytest.mark.parametrize("case", CASES, ids=[f"golden-{i + 1}" for i in range(len(CASES))])
async def test_the_model_produces_a_valid_interpretation(
    case: dict[str, object], build: Callable[..., Built], tmp_path: Path
) -> None:
    built = build(gens=make_gens(int(case.get("attempts", 8))))
    pack = [t for t in tool_pack(built.state) if t.name == "propose_interpretation"]
    config = ChatConfig(
        agent_name="visual-generation", system_prompt=system_prompt(), tool_pack=lambda: pack,
        default_budget=BudgetEnvelope(max_cost_usd=0.5),
    )
    session = Session(config, ShellSettings(agent_data_dir=tmp_path / "data"),
                      make_engine("claude", "claude-haiku-4-5"))
    await session.start()
    events = await drain(session, str(case["feedback"]))
    await session.close()

    assert isinstance(events[-1], TurnEnd) and events[-1].reason == "complete", events[-1]
    finished = [e for e in events if isinstance(e, ToolCallFinished) and e.name == "propose_interpretation"]
    good = [e for e in finished if not e.result.is_error]
    assert good, [e.result.text for e in finished] or "the model never called propose_interpretation"

    fi = FeedbackInterpretation.model_validate(good[-1].result.data)
    assert fi.observations, "an interpretation with no observations"
    resolver = LabelResolver(built.store.list_generations.side_effect(project="demo"))
    for label in case.get("context_labels", []):  # type: ignore[attr-defined]
        if resolver.resolve(label).gen_id is None:
            assert any(label in q for q in fi.open_questions), f"{label!r} did not reach open_questions"
    for o in fi.observations:
        if o.label and o.resolved_gen_id is None:
            assert any(o.label in q for q in fi.open_questions)
