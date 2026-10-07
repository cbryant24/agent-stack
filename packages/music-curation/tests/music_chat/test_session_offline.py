"""The real tool pack inside a real agent-shell Session (scripted engine, no model, no network):
every write shows the gate, and what was stored afterwards matches what the director decided."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from agent_shell.config import ShellSettings
from agent_shell.engine.fake import Call, FakeEngine, Say
from agent_shell.guard.gate import AutoConfirmer, Decision
from agent_shell.session.api import Session
from agent_shell.testing import drain

import music_curation.chat.tools.craft as craft_mod
import music_curation.seed_ingestion as si
from music_curation.chat.config import build_chat_config, system_prompt
from music_curation.models import MusicResult, SunoPrompt

from .conftest import Built, make_gens, seed_session  # type: ignore[import-not-found]
from .test_reachability import EXPECTED  # type: ignore[import-not-found]

pytestmark = pytest.mark.asyncio


def session(b: Built, script: list[list[Say | Call]], tmp_path: Path, *, dry_run: bool = False,
            confirmer: AutoConfirmer | None = None, tool_budget: float = 0.5) -> Session:
    s = Session(build_chat_config(b.state),
                ShellSettings(agent_data_dir=tmp_path / "shell", dry_run=dry_run, tool_budget_usd=tool_budget),
                FakeEngine(script), confirmer=confirmer or AutoConfirmer())
    b.state.session = s
    return s


def report_call(gen_id: str, **over: Any) -> list[list[Say | Call]]:
    return [[Call(name="report", args={"generation": gen_id, "reaction": "loved", "rating": 5, **over})]]


def result(cost: float = 0.04) -> MusicResult:
    return MusicResult(prompts=[SunoPrompt(style_field="lo-fi, 80 BPM")], suggested_titles=["Night"], theory_reasoning="t",
                       run_id="r", status="completed", cost_usd=cost, items_processed=1, wall_time_sec=1.0,
                       generation_ids=["gen-1"])


async def test_the_session_exposes_exactly_the_chat_tools(build: Callable[..., Built], tmp_path: Path) -> None:
    s = session(build(), [], tmp_path)
    await s.start()
    assert set(s.registry.names()) == EXPECTED and s.config.agent_name == "music-curation"
    assert s.config.on_session_end is not None


async def test_accept_records_the_reaction_once(build: Callable[..., Built], tmp_path: Path) -> None:
    gens = make_gens(2)
    b = build(gens=gens)
    c = AutoConfirmer("accept")
    s = session(b, report_call(gens[0].entry_id), tmp_path, confirmer=c)
    await s.start()
    await drain(s, "go")
    assert b.names == ["update_generation_reaction"] and gens[0].reaction == "loved"
    req = c.requests[0]
    assert req.tool == "report" and req.allowed == ("accept", "reject", "edit", "defer")
    assert "Record reaction on Track 1 (00000001): loved ★5" in (req.preview or "")


async def test_reject_edit_defer_and_dry_run(build: Callable[..., Built], tmp_path: Path) -> None:
    gens = make_gens(4)
    b = build(gens=gens)
    s = session(b, report_call(gens[0].entry_id), tmp_path, confirmer=AutoConfirmer("reject"))
    await s.start()
    await drain(s, "go")
    assert b.writes == [] and gens[0].reaction == "pending"

    edited = {"generation": gens[1].entry_id, "reaction": "liked", "rating": 3}
    s = session(b, report_call(gens[1].entry_id), tmp_path, confirmer=AutoConfirmer(Decision(kind="edit", payload=edited)))
    await s.start()
    await drain(s, "go")
    ((args, kwargs),) = b.wrote("update_generation_reaction")
    assert args[1] == "liked" and kwargs["rating"] == 3
    assert s.audit is not None and s.audit.read()[0]["decision"] == "edit"

    b.writes.clear()
    s = session(b, report_call(gens[2].entry_id), tmp_path, confirmer=AutoConfirmer("defer"))
    await s.start()
    await drain(s, "go")
    drafts = list((tmp_path / "shell" / "drafts" / "music-curation").glob("*.json"))
    assert b.writes == [] and len(drafts) == 1 and gens[2].entry_id in drafts[0].read_text()

    c = AutoConfirmer()
    s = session(b, report_call(gens[3].entry_id), tmp_path, dry_run=True, confirmer=c)
    await s.start()
    events = await drain(s, "go")
    text = next(e.result.text for e in events if hasattr(e, "result"))
    assert text.startswith("[dry-run] would run report: Record reaction on Track 4") and b.writes == [] and c.requests == []


async def test_a_report_that_would_fail_never_reaches_the_director(build: Callable[..., Built], tmp_path: Path) -> None:
    b = build(gens=make_gens(1))
    c = AutoConfirmer("accept")
    s = session(b, report_call("no-such-id"), tmp_path, confirmer=c)
    await s.start()
    await drain(s, "go")
    assert c.requests == [] and b.writes == []
    assert s.audit is not None and s.audit.read()[0]["decision"] == "precheck_failed"


async def test_generate_runs_within_budget_without_asking_and_asks_over_it(
    build: Callable[..., Built], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = AsyncMock(return_value=result(0.04))
    monkeypatch.setattr(craft_mod, "_curate", spy)
    script = [[Call(name="generate", args={"request": "lo-fi"})]]
    b = build()
    c = AutoConfirmer()
    s = session(b, script, tmp_path, confirmer=c)
    await s.start()
    await drain(s, "go")
    assert spy.await_count == 1 and c.requests == [] and s.budgets.tool.spent == pytest.approx(0.04)

    c = AutoConfirmer("reject")
    s = session(b, script, tmp_path, confirmer=c, tool_budget=0.05)        # the $0.10 estimate does not fit
    await s.start()
    await drain(s, "go")
    assert spy.await_count == 1 and c.requests[0].tool == "generate" and "exceeds tool budget" in (c.requests[0].warning or "")

    s = session(b, script, tmp_path, dry_run=True)
    await s.start()
    events = await drain(s, "go")
    assert spy.await_count == 1
    assert next(e.result.text for e in events if hasattr(e, "result")).startswith("[dry-run] would run generate")


async def test_a_seed_import_is_one_confirmed_write(
    build: Callable[..., Built], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "seed.md"
    path.write_text("# seed\n")
    monkeypatch.setattr(si, "parse_file", lambda p: seed_session())
    args = {"path": str(path), "ingest_facts": False,
            "taste": [{"n": i, "decision": "skip"} for i in (1, 2, 3)],
            "templates": [{"n": 1, "accept": False}, {"n": 2, "accept": False}]}
    b = build()
    s = session(b, [[Call(name="seed_ingest", args=args)]], tmp_path, confirmer=AutoConfirmer("reject"))
    await s.start()
    await drain(s, "go")
    assert b.writes == []

    c = AutoConfirmer("accept")
    s = session(b, [[Call(name="seed_ingest", args=args)]], tmp_path, confirmer=c)
    await s.start()
    await drain(s, "go")
    assert len(c.requests) == 1 and "Suno facts: 3 NOT written" in (c.requests[0].preview or "")
    assert b.names == ["upsert_taste_bulk", "upsert_templates_bulk", "upsert_generations_bulk"]   # explicit items + facts-as-generations only


async def test_a_proposed_reaction_left_unwritten_is_offered_at_exit(build: Callable[..., Built], tmp_path: Path) -> None:
    gens = make_gens(1)
    b = build(gens=gens)
    s = session(b, [[Call(name="propose_reaction", args={
        "generation": "latest", "reaction": "loved", "raw_feedback": "this is the one",
        "taste_lessons": [{"statement": "dusty rhodes chords", "valence": "positive", "scope": "instrumentation"}]})]], tmp_path)
    await s.start()
    await drain(s, "feedback")
    proposals = await s.close()
    assert [p.tool for p in proposals] == ["report", "taste_add"] and b.writes == []
    await s.start(s.session_id)
    r = await s.apply_proposal(proposals[0])
    assert not r.is_error and b.names == ["update_generation_reaction"] and b.state.unwritten_proposals()[0].tool == "taste_add"


async def test_the_prompt_fits_its_budget_names_only_real_tools_and_states_the_rules(build: Callable[..., Built]) -> None:
    from music_curation.chat.tools import tool_pack

    p = system_prompt()
    assert len(p) / 4 <= 1200, f"~{len(p) // 4} tokens"
    names = {t.name for t in tool_pack(build().state)}
    mentioned = {w.strip("`.,;:()") for w in p.split() if w.startswith("`") and w.strip("`.,;:()").replace("_", "").isalpha()}
    reactions = {"loved", "liked", "liked_with_changes", "disliked", "prompt_failed", "copyright_blocked", "never_ran",
                 "lost_track", "notes", "context", "latest"}
    assert mentioned - reactions <= names, mentioned - reactions - names
    for phrase in ("Suno has no API", "it stores nothing", "Do not swap them", "Always propose before any write",
                   "Never decide one yourself"):
        assert phrase in p
