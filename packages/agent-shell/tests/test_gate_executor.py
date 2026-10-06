from __future__ import annotations

from pathlib import Path

import pytest

from agent_runtime.models import BudgetEnvelope
from agent_shell.audit.log import AuditLog
from agent_shell.guard.gate import AutoConfirmer, Decision, Gate, SessionBudgets
from agent_shell.tools.executor import Executor
from agent_shell.tools.registry import EffectClass
from agent_shell.testing import Counter, make_tool

pytestmark = pytest.mark.asyncio


def build(
    tmp_path: Path, confirmer: AutoConfirmer, *, dry_run: bool = False, tool_usd: float = 0.5,
    gpu_usd: float = 1.0,
) -> tuple[Executor, SessionBudgets, AuditLog]:
    budgets = SessionBudgets.from_envelope(
        BudgetEnvelope(max_cost_usd=1.0), tool_usd=tool_usd, gpu_usd=gpu_usd
    )
    audit = AuditLog(tmp_path / "audit.jsonl")
    ex = Executor(Gate(confirmer, budgets), audit, tmp_path / "drafts", dry_run=lambda: dry_run)
    return ex, budgets, audit


async def test_read_tools_run_without_asking(tmp_path: Path, counter: Counter) -> None:
    c = AutoConfirmer()
    ex, _, _ = build(tmp_path, c)
    res = await ex.run(make_tool("r", EffectClass.READ, counter), {"text": "hi"})
    assert res.text == "r ran hi" and c.requests == []


async def test_gpu_accept_runs_and_charges_gpu_budget(tmp_path: Path, counter: Counter) -> None:
    c = AutoConfirmer("accept")
    ex, budgets, audit = build(tmp_path, c)
    res = await ex.run(make_tool("g", EffectClass.GPU_SPEND, counter, cost=0.25, est=0.25), {})
    assert not res.is_error and counter.calls == ["x"]
    assert budgets.gpu.spent == 0.25 and budgets.tool.spent == 0 and budgets.repl.spent == 0
    req = c.requests[0]
    assert req.allowed == ("accept", "reject") and req.preview == "preview x" and req.args == {"text": "x"}
    assert audit.read()[0]["decision"] == "allow" and audit.read()[0]["cost_usd"] == 0.25


async def test_gpu_reject_runs_nothing(tmp_path: Path, counter: Counter) -> None:
    ex, budgets, audit = build(tmp_path, AutoConfirmer("reject"))
    res = await ex.run(make_tool("g", EffectClass.GPU_SPEND, counter, cost=0.25), {})
    assert counter.calls == [] and res.data == {"rejected": True} and budgets.gpu.spent == 0
    assert audit.read()[0]["decision"] == "reject"


async def test_gpu_edit_is_not_offered_so_it_counts_as_reject(tmp_path: Path, counter: Counter) -> None:
    ex, _, _ = build(tmp_path, AutoConfirmer(Decision(kind="edit", payload={"text": "y"})))
    await ex.run(make_tool("g", EffectClass.GPU_SPEND, counter), {})
    assert counter.calls == []


async def test_gpu_over_budget_shows_a_warning(tmp_path: Path, counter: Counter) -> None:
    c = AutoConfirmer("reject")
    ex, _, _ = build(tmp_path, c, gpu_usd=0.1)
    await ex.run(make_tool("g", EffectClass.GPU_SPEND, counter, est=0.25), {})
    assert c.requests[0].warning and "gpu" in c.requests[0].warning


async def test_destructive_always_asks(tmp_path: Path, counter: Counter) -> None:
    c = AutoConfirmer("reject")
    ex, _, _ = build(tmp_path, c)
    await ex.run(make_tool("d", EffectClass.DESTRUCTIVE_LOCAL, counter), {})
    assert len(c.requests) == 1 and counter.calls == []


async def test_memory_write_edit_runs_with_the_edited_args(tmp_path: Path, counter: Counter) -> None:
    c = AutoConfirmer(Decision(kind="edit", payload={"text": "edited"}))
    ex, _, audit = build(tmp_path, c)
    res = await ex.run(make_tool("m", EffectClass.MEMORY_WRITE, counter), {"text": "orig"})
    assert counter.calls == ["edited"] and res.text == "m ran edited"
    assert c.requests[0].allowed == ("accept", "reject", "edit", "defer")
    assert audit.read()[0]["decision"] == "edit"


async def test_memory_write_edit_that_fails_validation_is_an_error_result(
    tmp_path: Path, counter: Counter
) -> None:
    ex, _, audit = build(tmp_path, AutoConfirmer(Decision(kind="edit", payload={"text": 5})))
    res = await ex.run(make_tool("m", EffectClass.MEMORY_WRITE, counter), {})
    assert res.is_error and "ValidationError" in res.text and counter.calls == []
    assert audit.read()[0]["decision"] == "edit_invalid"


async def test_memory_write_defer_queues_a_draft_once(tmp_path: Path, counter: Counter) -> None:
    ex, _, _ = build(tmp_path, AutoConfirmer("defer", "defer"))
    tool = make_tool("m", EffectClass.MEMORY_WRITE, counter)
    r1 = await ex.run(tool, {"text": "same"})
    await ex.run(tool, {"text": "same"})
    assert counter.calls == [] and r1.data == {"deferred": True}
    assert len(list((tmp_path / "drafts").glob("*.json"))) == 1


async def test_dry_run_never_calls_the_handler_or_asks(tmp_path: Path, counter: Counter) -> None:
    c = AutoConfirmer("accept")
    ex, _, audit = build(tmp_path, c, dry_run=True)
    for effect in (EffectClass.GPU_SPEND, EffectClass.MEMORY_WRITE, EffectClass.DESTRUCTIVE_LOCAL,
                   EffectClass.LLM_SPEND):
        res = await ex.run(make_tool(effect.value, effect, counter), {})
        assert res.text.startswith("[dry-run] would run") and "preview x" in res.text
    assert counter.calls == [] and c.requests == []
    assert {r["decision"] for r in audit.read()} == {"dry_run"}


async def test_dry_run_still_runs_reads(tmp_path: Path, counter: Counter) -> None:
    ex, _, _ = build(tmp_path, AutoConfirmer(), dry_run=True)
    await ex.run(make_tool("r", EffectClass.READ, counter), {})
    assert counter.calls == ["x"]


async def test_llm_spend_within_budget_does_not_prompt(tmp_path: Path, counter: Counter) -> None:
    c = AutoConfirmer()
    ex, budgets, _ = build(tmp_path, c)
    await ex.run(make_tool("l", EffectClass.LLM_SPEND, counter, cost=0.2, est=0.2), {})
    assert c.requests == [] and budgets.tool.spent == 0.2


async def test_llm_spend_over_budget_prompts_and_reject_stops_it(tmp_path: Path, counter: Counter) -> None:
    c = AutoConfirmer("reject")
    ex, _, _ = build(tmp_path, c, tool_usd=0.1)
    await ex.run(make_tool("l", EffectClass.LLM_SPEND, counter, est=0.2), {})
    assert len(c.requests) == 1 and counter.calls == []


async def test_handler_exception_becomes_an_error_result_and_is_audited(
    tmp_path: Path, counter: Counter
) -> None:
    ex, _, audit = build(tmp_path, AutoConfirmer())
    res = await ex.run(make_tool("r", EffectClass.READ, counter, boom=True), {})
    assert res.is_error and res.text == "RuntimeError: kaput"
    rec = audit.read()[0]
    assert rec["is_error"] and rec["decision"] == "error"


async def test_invalid_input_is_an_error_result(tmp_path: Path, counter: Counter) -> None:
    ex, _, audit = build(tmp_path, AutoConfirmer())
    res = await ex.run(make_tool("r", EffectClass.READ, counter), {"text": 123})
    assert res.is_error and counter.calls == [] and audit.read()[0]["decision"] == "invalid"


async def test_bound_spec_goes_through_the_gate(tmp_path: Path, counter: Counter) -> None:
    """The path engines and MCP clients use: same gate, same audit."""
    c = AutoConfirmer("reject")
    ex, _, audit = build(tmp_path, c)
    bound = ex.bind(make_tool("g", EffectClass.GPU_SPEND, counter))
    res = await bound.handler({"text": "z"})
    assert res.data == {"rejected": True} and len(audit.read()) == 1


async def test_budgets_are_independent() -> None:
    budgets = SessionBudgets.from_envelope(BudgetEnvelope(max_cost_usd=1.0), tool_usd=5.0, gpu_usd=2.0)
    assert budgets.tool.max_usd == 1.0  # child envelope is capped by the parent
    budgets.gpu.charge(2.0)
    assert budgets.gpu.exhausted and not budgets.repl.exhausted and not budgets.tool.exhausted
