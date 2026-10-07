"""Live check of propose_interpretation over real feedback strings (golden/feedback.jsonl).

Skipped unless AGENT_SHELL_LIVE=1 (it calls a real model, a few cents per string):

    op run --env-file=.env -- env AGENT_SHELL_LIVE=1 uv run pytest packages/visual-generation -m live -v

For each string a real engine either asks for what it needs (no reaction given) or calls
propose_interpretation and gets a valid proposal: the director's words kept verbatim, and any label
that does not resolve surfaced as an open question rather than guessed. Nothing is written (no
write tool is in the pack).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from agent_runtime.models import BudgetEnvelope
from agent_shell.config import ChatConfig, ShellSettings
from agent_shell.engine.base import TextDelta, ToolCallFinished, TurnEnd
from agent_shell.engine.factory import make_engine
from agent_shell.session.api import Session
from agent_shell.testing import drain

from visual_generation.chat.config import system_prompt
from visual_generation.chat.labels import LabelResolver
from visual_generation.chat.tools import tool_pack

from .conftest import Built, make_gens  # type: ignore[import-not-found]

pytestmark = [pytest.mark.live, pytest.mark.asyncio]

GOLDEN = Path(__file__).parent / "golden" / "feedback.jsonl"
CASES = [json.loads(x) for x in GOLDEN.read_text().splitlines() if x.strip() and not x.startswith("#")]


@pytest.mark.parametrize("case", CASES, ids=[f"golden-{i + 1}" for i in range(len(CASES))])
async def test_the_model_produces_a_valid_proposal_or_asks(
    case: dict[str, object], build: Callable[..., Built], tmp_path: Path
) -> None:
    built = build(gens=make_gens(int(case.get("attempts", 8))))
    pack = [t for t in tool_pack(built.state) if t.name == "propose_interpretation"]   # propose only: no writes exist
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
    reply = "".join(e.text for e in events if isinstance(e, TextDelta))
    calls = [e for e in events if isinstance(e, ToolCallFinished) and e.name == "propose_interpretation"]
    good = [c for c in calls if not c.result.is_error]
    if not good:
        # Acceptable only if the model asked for what it needed (e.g. the director's reaction).
        assert "?" in reply, [c.result.text for c in calls] or "no tool call and no question"
        return

    last = good[-1].result.data
    assert last["raw_feedback"].strip() in str(case["feedback"]), "the director's words must be kept verbatim"
    assert last["reaction"] in {"loved", "liked", "liked_with_changes", "disliked", "render_failed"}
    resolver = LabelResolver(built.gens)
    for label in case.get("context_labels", []):  # type: ignore[attr-defined]
        if resolver.resolve(label).gen_id is None:
            flagged = any(label in q for q in last["open_questions"]) or label in reply
            assert flagged, f"{label!r} does not resolve and was neither asked about nor flagged"
