"""Accepted end-of-session proposals are carried out through their tool; the audit log records
what was written."""

from __future__ import annotations

import io
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from prompt_toolkit import PromptSession
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from rich.console import Console

from agent_shell.engine.fake import Call, Say
from agent_shell.guard.gate import AutoConfirmer, Decision
from agent_shell.proposals import Proposal, walk_proposals
from agent_shell.repl.app import ShellApp, _bindings
from agent_shell.session.api import Session
from agent_shell.testing import Counter, drain

pytestmark = pytest.mark.asyncio
Make = Callable[..., Session]


def prop(text: str = "p1", **kw: Any) -> Proposal:
    return Proposal(kind="note", summary=f"write {text}", payload={"text": text}, tool="mem", **kw)


async def test_apply_runs_the_tool_without_the_gate_and_audits_it(make_session: Make, counter: Counter) -> None:
    c = AutoConfirmer()                                   # would reject if the gate were consulted
    s = make_session(confirmer=c)
    await s.start()
    res = await s.apply_proposal(prop("hello"))
    assert res.text == "mem ran hello" and counter.calls == ["hello"] and c.requests == []
    assert s.audit is not None
    rec = [r for r in s.audit.read() if r["kind"] == "tool_call"][-1]
    assert rec["decision"] == "proposal_accept" and rec["tool"] == "mem"


async def test_apply_still_validates_and_honors_dry_run(make_session: Make, counter: Counter) -> None:
    s = make_session()
    await s.start()
    bad = await s.apply_proposal(Proposal(kind="n", summary="s", payload={"text": 5}, tool="mem"))
    assert bad.is_error and "ValidationError" in bad.text and counter.calls == []
    s.dry_run = True
    dry = await s.apply_proposal(prop("x"))
    assert dry.text.startswith("[dry-run] would run mem") and counter.calls == []


async def test_apply_needs_a_known_tool(make_session: Make) -> None:
    s = make_session()
    await s.start()
    assert (await s.apply_proposal(Proposal(kind="n", summary="s"))).is_error
    unknown = await s.apply_proposal(Proposal(kind="n", summary="s", tool="nope"))
    assert unknown.is_error and "unknown tool" in unknown.text


async def test_audit_records_the_written_ids_and_artifacts(make_session: Make) -> None:
    from agent_shell.testing import make_tool
    from agent_shell.tools.registry import EffectClass, ToolResult, ToolSpec

    async def write(a: Any) -> ToolResult:
        return ToolResult(text="wrote", data={"eval_id": "e-123", "count": 1}, artifacts=["/tmp/x.json"])

    tool = ToolSpec(name="w", description="w", input_model=make_tool("t", EffectClass.READ, Counter()).input_model,
                    effect=EffectClass.MEMORY_WRITE, handler=write)
    s = make_session([[Call(name="w", args={})]], tools=[tool], confirmer=AutoConfirmer("accept"))
    await s.start()
    await drain(s, "go")
    assert s.audit is not None
    rec = s.audit.read()[0]
    assert rec["result_data"] == {"eval_id": "e-123", "count": 1} and rec["artifacts"] == ["/tmp/x.json"]
    assert rec["args"] == {"text": "x"} and rec["decision"] == "allow"


@contextmanager
def app(session: Session, typed: str) -> Iterator[tuple[ShellApp, io.StringIO]]:
    out = io.StringIO()
    with create_pipe_input() as pipe:
        pipe.send_text(typed)
        prompt: PromptSession[str] = PromptSession(
            input=pipe, output=DummyOutput(), key_bindings=_bindings(), multiline=True)
        yield ShellApp(session, console=Console(file=out, force_terminal=False, width=100),
                       prompt=prompt), out


async def test_the_repl_applies_accepted_proposals_and_leaves_the_rest(
    make_session: Make, counter: Counter, settings: Any
) -> None:
    props = [prop("a"), prop("b"), prop("c"), prop("d")]
    s = make_session([[Say(text="hi")]], on_end=lambda transcript: props, broker=False)
    # answers: accept a, edit b, defer c, reject d
    typed = "hello\r/exit\r" + "y\r" + "e\r" + json.dumps({"text": "b-edited"}) + "\r" + "d\r" + "n\r"
    with app(s, typed) as (shell, out):
        report = await shell.run()
    assert counter.calls == ["a", "b-edited"]                      # accepted + edited ran; deferred/rejected did not
    assert [p.summary for p in report.deferred] == ["write c"] and [p.summary for p in report.skipped] == ["write d"]
    text = out.getvalue()
    assert "mem: mem ran a" in text and "mem: mem ran b-edited" in text and "accepted 2" in text
    recs = [r for r in s.audit.read() if r["decision"] == "proposal_accept"] if s.audit else []
    assert [r["args"]["text"] for r in recs] == ["a", "b-edited"]
    draft = next((settings.agent_data_dir / "drafts" / "t").glob("*.json"))
    saved = json.loads(draft.read_text())
    assert saved["tool"] == "mem" and saved["payload"] == {"text": "c"}      # a later session can re-run it


async def test_a_proposal_without_a_tool_is_not_applied_by_the_repl(make_session: Make, counter: Counter) -> None:
    s = make_session([[Say(text="hi")]], on_end=lambda t: [Proposal(kind="n", summary="manual", payload={"text": "z"})])
    with app(s, "hello\r/exit\ry\r") as (shell, _):
        report = await shell.run()
    assert len(report.accepted) == 1 and counter.calls == []


async def test_walk_proposals_defer_keeps_the_tool_in_the_draft(tmp_path: Path) -> None:
    await walk_proposals([prop("q")], AutoConfirmer(Decision(kind="defer")), tmp_path / "drafts")
    saved = json.loads(next((tmp_path / "drafts").glob("*.json")).read_text())
    assert saved["tool"] == "mem"
