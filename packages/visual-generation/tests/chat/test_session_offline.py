"""The real tool pack inside a real agent-shell Session (scripted engine, no model, no network):
every write shows the gate, and what was stored afterwards matches what the director decided."""

from __future__ import annotations

import io
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from agent_runtime.models import BudgetEnvelope
from agent_shell.config import ShellSettings
from agent_shell.engine.base import ToolCallFinished
from agent_shell.engine.fake import Call, FakeEngine, Say
from agent_shell.guard.gate import AutoConfirmer, Decision
from agent_shell.repl.app import ShellApp, _bindings
from agent_shell.session.api import Session
from agent_shell.testing import drain
from prompt_toolkit import PromptSession
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from rich.console import Console

import visual_generation.chat.tools.craft as craft_mod
from visual_generation.chat.config import build_chat_config
from visual_generation.evaluation import EXECUTION_TRUTH_ENV
from visual_generation.models import DraftResult, TechniqueLesson, VisualSpec

from .conftest import Built, make_gens  # type: ignore[import-not-found]

pytestmark = pytest.mark.asyncio

EV = dict(generation="attempt-03", raw_feedback="the face reads plastic", reaction="disliked", rating=2,
          findings=[dict(layer="conditioning_asset", evidence="observed", statement="button eyes read as paint",
                         basis="attempt-03 asset")])


@pytest.fixture(autouse=True)
def _unset_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(EXECUTION_TRUTH_ENV, raising=False)


def session(b: Built, script: list[list[Say | Call]], tmp_path: Path, *, dry_run: bool = False,
            confirmer: AutoConfirmer | None = None, tool_budget: float = 0.5) -> Session:
    b.state.session = None
    s = Session(build_chat_config(b.state),
                ShellSettings(agent_data_dir=tmp_path / "shell", dry_run=dry_run, tool_budget_usd=tool_budget),
                FakeEngine(script), confirmer=confirmer or AutoConfirmer())
    b.state.session = s
    return s


def drafted(cost: float = 0.04) -> DraftResult:
    return DraftResult(spec=VisualSpec(prompt="p", heading="h"), template_name="z-image-turbo",
                       template_modality="text2img", status="completed", cost_usd=cost)


def call_record(**over: Any) -> list[list[Say | Call]]:
    return [[Call(name="record_evaluation", args={**EV, **over})]]


# ── the gate, path by path, judged by what was stored ────────────────────────


async def test_accept_writes_exactly_one_evaluation_and_sets_the_reaction(build: Callable[..., Built], tmp_path: Path) -> None:
    gens = make_gens(8)
    b = build(gens=gens, allow_writes=True)
    c = AutoConfirmer("accept")
    s = session(b, call_record(), tmp_path, confirmer=c)
    await s.start()
    await drain(s, "go")
    assert len(b.evals) == 1 and gens[2].reaction == "disliked" and b.writes.count("upsert_evaluation") == 1
    req = c.requests[0]
    assert req.tool == "record_evaluation" and req.allowed == ("accept", "reject", "edit", "defer")
    assert "the face reads plastic" in (req.preview or "") and "attempt-03" in (req.preview or "")


async def test_reject_changes_nothing_and_the_proposal_stays_for_exit(build: Callable[..., Built], tmp_path: Path) -> None:
    gens = make_gens(8)
    b = build(gens=gens, allow_writes=True)
    s = session(b, [[Call(name="propose_interpretation", args=EV)], *call_record()], tmp_path,
                confirmer=AutoConfirmer("reject"))
    await s.start()
    await drain(s, "feedback")
    await drain(s, "write it")
    assert b.writes == [] and b.evals == [] and gens[2].reaction == "pending"
    assert [p.tool for p in b.state.unwritten_proposals()] == ["record_evaluation"]


async def test_edit_records_the_edited_arguments_not_the_originals(build: Callable[..., Built], tmp_path: Path) -> None:
    b = build(gens=make_gens(8), allow_writes=True)
    s = session(b, call_record(), tmp_path, confirmer=AutoConfirmer(Decision(kind="edit", payload={**EV, "rating": 4, "reaction": "liked_with_changes"})))
    await s.start()
    await drain(s, "go")
    (e,) = b.evals
    assert (e.rating, e.reaction) == (4, "liked_with_changes")
    assert s.audit is not None and s.audit.read()[0]["decision"] == "edit"


async def test_defer_writes_nothing_and_queues_a_self_contained_draft(build: Callable[..., Built], tmp_path: Path) -> None:
    b = build(gens=make_gens(8), allow_writes=True)
    s = session(b, call_record(), tmp_path, confirmer=AutoConfirmer("defer"))
    await s.start()
    await drain(s, "go")
    assert b.writes == [] and b.evals == []
    drafts = list((tmp_path / "shell" / "drafts" / "visual-generation").glob("*.json"))
    assert len(drafts) == 1
    saved = json.loads(drafts[0].read_text())
    assert saved["payload"]["raw_feedback"] == EV["raw_feedback"] and saved["payload"]["reaction"] == "disliked"


async def test_dry_run_describes_the_write_and_stores_nothing(build: Callable[..., Built], tmp_path: Path) -> None:
    b = build(gens=make_gens(8), allow_writes=True)
    c = AutoConfirmer("accept")
    s = session(b, call_record(), tmp_path, dry_run=True, confirmer=c)
    await s.start()
    events = await drain(s, "go")
    fin = next(e for e in events if isinstance(e, ToolCallFinished))
    assert fin.result.text.startswith("[dry-run] would run record_evaluation") and "the face reads plastic" in fin.result.text
    assert b.writes == [] and c.requests == []


async def test_a_record_that_would_be_refused_never_reaches_the_director(build: Callable[..., Built], tmp_path: Path) -> None:
    b = build(gens=make_gens(8), allow_writes=True)
    c = AutoConfirmer("accept")
    s = session(b, call_record(change=["set denoise to 0.35"]), tmp_path, confirmer=c)
    await s.start()
    events = await drain(s, "go")
    fin = next(e for e in events if isinstance(e, ToolCallFinished))
    assert fin.result.is_error and "open_parameter" in fin.result.text
    assert c.requests == [] and b.writes == []                                   # not asked, not written
    assert s.audit is not None and s.audit.read()[0]["decision"] == "precheck_failed"


async def test_destructive_tools_show_the_exact_item_and_reject_leaves_it(build: Callable[..., Built], tmp_path: Path) -> None:
    le = TechniqueLesson(statement="strength pairs isolate two identities", valence="positive", scope="model",
                         confirmed=True, entry_id="6f5638ea-0000-0000-0000-000000000001")
    b = build(lessons=[le], allow_writes=True)
    c = AutoConfirmer("reject", "accept")
    s = session(b, [[Call(name="lesson_rm", args={"lesson": "6f5638ea"})], [Call(name="lesson_rm", args={"lesson": "6f5638ea"})]],
                tmp_path, confirmer=c)
    await s.start()
    await drain(s, "one")
    assert b.lessons == [le] and c.requests[0].allowed == ("accept", "reject")      # destructive: y/n only
    assert "strength pairs isolate two identities" in (c.requests[0].preview or "")
    await drain(s, "two")
    assert b.lessons == []


async def test_the_audit_log_alone_reconstructs_what_was_written_and_why(build: Callable[..., Built], tmp_path: Path) -> None:
    gens = make_gens(8)
    b = build(gens=gens, allow_writes=True)
    s = session(b, call_record(change=["softer light"]), tmp_path, confirmer=AutoConfirmer("accept"))
    await s.start()
    await drain(s, "go")
    assert s.audit is not None
    rec = next(r for r in s.audit.read() if r["kind"] == "tool_call")
    assert rec["tool"] == "record_evaluation" and rec["effect"] == "memory_write" and rec["decision"] == "allow"
    assert rec["args"]["raw_feedback"] == EV["raw_feedback"]                         # the director's words (why)
    assert rec["args"]["findings"][0]["statement"] == "button eyes read as paint"
    assert rec["result_data"]["evaluation_id"] == b.evals[0].entry_id                # what was written
    assert rec["result_data"]["gen_id"] == gens[2].entry_id and rec["result_data"]["agent_status"] == "unresolved"
    assert rec["provider"] == "fake" and "Wrote evaluation" in rec["summary"]


# ── the end-of-session flow ───────────────────────────────────────────────────


@contextmanager
def repl(s: Session, typed: str) -> Iterator[tuple[ShellApp, io.StringIO]]:
    out = io.StringIO()
    with create_pipe_input() as pipe:
        pipe.send_text(typed)
        prompt: PromptSession[str] = PromptSession(input=pipe, output=DummyOutput(), key_bindings=_bindings(), multiline=True)
        yield ShellApp(s, console=Console(file=out, force_terminal=False, width=110), prompt=prompt), out


async def test_an_unwritten_proposal_is_offered_at_exit_and_applied_when_accepted(
    build: Callable[..., Built], tmp_path: Path
) -> None:
    gens = make_gens(8)
    b = build(gens=gens, allow_writes=True)
    s = session(b, [[Call(name="propose_interpretation", args=EV)]], tmp_path)
    with repl(s, "feedback\r/exit\ry\r") as (app, out):
        report = await app.run()
    assert len(report.accepted) == 1 and len(b.evals) == 1 and gens[2].reaction == "disliked"
    assert "record_evaluation:" in out.getvalue() and "Wrote evaluation" in out.getvalue()
    assert s.audit is not None
    assert [r["decision"] for r in s.audit.read() if r["tool"] == "record_evaluation"] == ["proposal_accept"]
    assert b.state.unwritten_proposals() == []


async def test_exit_proposals_can_be_deferred_or_skipped(build: Callable[..., Built], tmp_path: Path) -> None:
    b = build(gens=make_gens(8), allow_writes=True)
    s = session(b, [[Call(name="propose_interpretation", args=EV)]], tmp_path)
    with repl(s, "feedback\r/exit\rd\r") as (app, _):
        report = await app.run()
    assert b.writes == [] and len(report.deferred) == 1
    assert len(list((tmp_path / "shell" / "drafts" / "visual-generation").glob("*.json"))) == 1


# ── Phase 3 behavior still holds with the write tools present ────────────────


async def test_a_draft_within_budget_runs_without_asking_and_charges_the_tool_budget(
    build: Callable[..., Built], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = AsyncMock(return_value=drafted(0.04))
    monkeypatch.setattr(craft_mod, "_draft", spy)
    c = AutoConfirmer()
    s = session(build(), [[Call(name="draft", args={"intent": "fog"})]], tmp_path, confirmer=c)
    await s.start()
    await drain(s, "go")
    assert spy.await_count == 1 and c.requests == [] and s.budgets.tool.spent == pytest.approx(0.04)


async def test_a_draft_that_would_exceed_the_tool_budget_asks_first(
    build: Callable[..., Built], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = AsyncMock(return_value=drafted())
    monkeypatch.setattr(craft_mod, "_draft", spy)
    c = AutoConfirmer("reject")
    s = session(build(), [[Call(name="draft", args={"intent": "fog"})]], tmp_path, confirmer=c, tool_budget=0.01)
    await s.start()
    await drain(s, "go")
    assert len(c.requests) == 1 and "exceeds tool budget" in (c.requests[0].warning or "") and spy.await_count == 0


async def test_dry_run_describes_craft_tools_and_calls_no_model(
    build: Callable[..., Built], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = AsyncMock(return_value=drafted())
    monkeypatch.setattr(craft_mod, "_draft", spy)
    s = session(build(), [[Call(name="draft", args={"intent": "fog"})]], tmp_path, dry_run=True)
    await s.start()
    events = await drain(s, "go")
    assert next(e for e in events if isinstance(e, ToolCallFinished)).result.text.startswith("[dry-run] would run draft")
    assert spy.await_count == 0


async def test_read_tools_never_prompt(build: Callable[..., Built], tmp_path: Path) -> None:
    c = AutoConfirmer()
    s = session(build(gens=make_gens(2)), [[Call(name="recall", args={"query": "x"}), Call(name="digest", args={})]], tmp_path, confirmer=c)
    await s.start()
    await drain(s, "go")
    assert c.requests == []


async def test_the_session_exposes_exactly_the_chat_tools(build: Callable[..., Built], tmp_path: Path) -> None:
    from .test_reachability import EXPECTED  # type: ignore[import-not-found]

    s = session(build(), [], tmp_path)
    await s.start()
    assert set(s.registry.names()) == EXPECTED
    assert s.config.on_session_end is not None and s.budgets.gpu.max_usd == 0.0
    assert isinstance(s.config.default_budget, BudgetEnvelope)
