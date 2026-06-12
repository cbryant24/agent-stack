"""Tests for the in-process sub-agent tools that wrap the other built agents.

Each tool calls its agent's existing library entry point in-process. For the
direction/draft tools (which accept a budget), we assert the call receives a
DERIVED CHILD budget; for the embedding-only recall tools (whose entry points
take no budget), we assert the entry point is invoked. All tools must record the
delegation on the active tracker.

Only the FREE / non-side-effecting ops are wrapped here — the costly, paid ops
(visual-generation `generate` = GPU/RunPod spend, voiceover-direction TTS
generation = ElevenLabs money) are deliberately NOT in the autonomous tool set,
so there are no tests for them here.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from agent_runtime import BudgetEnvelope
from agent_runtime.budget import BudgetTracker

from orchestrator import constants, tools


def _parent_envelope() -> BudgetEnvelope:
    return BudgetEnvelope(max_depth=2, max_cost_usd=1.0, max_wall_time_sec=600)


def _run_tool(invoke):
    """Run a tool invocation inside an active parent BudgetTracker.

    Returns (output_str, delegations_recorded). `invoke` is a zero-arg coroutine
    factory called inside the tracker context.
    """
    async def run() -> tuple[str, int]:
        async with BudgetTracker(_parent_envelope(), "orchestrator") as t:
            out = await invoke()
            return out, t.consumption.delegations

    return asyncio.run(run())


def _assert_child_budget(budget: object) -> None:
    """A budget produced by tools._child_budget() carries the sub-agent item cap
    and a cost no larger than the parent ceiling — i.e. it's a derived child."""
    assert isinstance(budget, BudgetEnvelope)
    assert budget.max_items == constants.SUBAGENT_MAX_ITEMS
    assert budget.max_cost_usd is not None and budget.max_cost_usd <= 1.0


# ── voiceover-direction ──────────────────────────────────────────────────────


class TestVoiceoverTools:
    def test_voiceover_direct_uses_child_budget_and_records(self) -> None:
        result = MagicMock(
            status="completed",
            cost_usd=0.02,
            output_path=None,
            overall_reasoning="paced the open",
            directed_script=MagicMock(sections=[]),
        )
        fake = AsyncMock(return_value=result)
        with patch("voiceover_direction.direct", fake), \
             patch("orchestrator.tools.record_delegation_decision") as rec:
            out, delegations = _run_tool(
                lambda: tools.voiceover_direct.ainvoke({"script_path": "seed/script.md"})
            )

        fake.assert_awaited_once()
        _assert_child_budget(fake.await_args.kwargs["budget"])
        assert delegations == 1
        assert rec.call_args.kwargs["decision"] == "delegate"
        assert rec.call_args.kwargs["collection"] == "voiceover_direction_memory"
        assert "status=completed" in out

    def test_voiceover_recall_calls_entry_point_and_records(self) -> None:
        ctx = MagicMock()
        ctx.is_empty.return_value = False
        ctx.prior_takes = [(0.9, MagicMock(text="a prior take"))]
        ctx.direction_lessons = []
        ctx.elevenlabs_facts = []
        ctx.tutorial_hits = []
        retrieve = AsyncMock(return_value=ctx)
        with patch("voiceover_direction.retrieval.retrieve_context", retrieve), \
             patch("voiceover_direction.VoiceoverDirectionStore", MagicMock()), \
             patch("agent_runtime.get_memory_store", MagicMock()), \
             patch("orchestrator.tools.record_delegation_decision") as rec:
            out, delegations = _run_tool(
                lambda: tools.voiceover_recall.ainvoke({"query": "narration pacing"})
            )

        retrieve.assert_awaited_once()
        assert delegations == 1
        assert rec.call_args.kwargs["collection"] == "voiceover_direction_memory"
        assert "a prior take" in out


# ── concept-script (stateless) ─────────────────────────────────────────────────


class TestConceptTools:
    def _result(self) -> MagicMock:
        return MagicMock(
            status="completed",
            cost_usd=0.015,
            script_path=None,
            brief=MagicMock(logline="A short film about latency", sections=[]),
        )

    def test_concept_draft_uses_child_budget_and_records(self) -> None:
        fake = AsyncMock(return_value=self._result())
        with patch("concept_script.draft", fake), \
             patch("orchestrator.tools.record_delegation_decision") as rec:
            out, delegations = _run_tool(
                lambda: tools.concept_draft.ainvoke({"seeds": "a tense heist"})
            )

        fake.assert_awaited_once()
        _assert_child_budget(fake.await_args.kwargs["budget"])
        assert delegations == 1
        assert rec.call_args.kwargs["collection"] == "concept_script"
        assert "logline: A short film about latency" in out

    def test_concept_shape_uses_child_budget_and_records(self) -> None:
        fake = AsyncMock(return_value=self._result())
        with patch("concept_script.shape", fake), \
             patch("orchestrator.tools.record_delegation_decision") as rec:
            out, delegations = _run_tool(
                lambda: tools.concept_shape.ainvoke({"transcript": "um, so basically..."})
            )

        fake.assert_awaited_once()
        _assert_child_budget(fake.await_args.kwargs["budget"])
        assert delegations == 1
        assert rec.call_args.kwargs["collection"] == "concept_script"


# ── visual-generation ───────────────────────────────────────────────────────


class TestVisualTools:
    def test_visual_draft_uses_child_budget_and_records(self) -> None:
        result = MagicMock(
            status="completed",
            cost_usd=0.03,
            missing_models=[],
            research_offer=None,
            overall_reasoning="settled the spec",
        )
        result.spec = MagicMock(heading="hero shot", model="flux-dev", prompt="a neon city")
        fake = AsyncMock(return_value=result)
        with patch("visual_generation.draft", fake), \
             patch("orchestrator.tools.record_delegation_decision") as rec:
            out, delegations = _run_tool(
                lambda: tools.visual_draft.ainvoke({"intent": "a neon city at night"})
            )

        fake.assert_awaited_once()
        _assert_child_budget(fake.await_args.kwargs["budget"])
        assert delegations == 1
        assert rec.call_args.kwargs["collection"] == "visual_generation_memory"
        assert "prompt: a neon city" in out

    def test_visual_recall_calls_entry_point_and_records(self) -> None:
        gens = [("id-1", 0.88, MagicMock())]
        recall = AsyncMock(return_value=(gens, [], []))
        with patch("visual_generation.recall", recall), \
             patch("visual_generation.render_recall", MagicMock(return_value="RENDERED")), \
             patch("orchestrator.tools.record_delegation_decision") as rec:
            out, delegations = _run_tool(
                lambda: tools.visual_recall.ainvoke({"query": "neon city"})
            )

        recall.assert_awaited_once()
        assert delegations == 1
        assert rec.call_args.kwargs["collection"] == "visual_generation_memory"
        assert out == "RENDERED"


# ── edit-brief (stateless) ──────────────────────────────────────────────────────


class TestEditBriefTools:
    def _result(self, *, dry_run: bool, cost: float = 0.0) -> MagicMock:
        music = MagicMock(file=None, bpm=None, bpm_source="none")
        provenance = MagicMock(project_id="script-draft", vo_takes=[], music=music, assets=[])
        brief = MagicMock(
            provenance=provenance,
            timeline=[MagicMock(), MagicMock()],
            beat_grid=None,
            sections=([] if dry_run else [MagicMock(), MagicMock()]),
            notations=["No voiceover takes discovered — timestamps are estimates."],
        )
        return MagicMock(
            brief=brief,
            brief_path=(None if dry_run else "script-draft.edit-brief.md"),
            status="completed",
            cost_usd=cost,
            dry_run=dry_run,
        )

    def test_edit_brief_discover_is_free_and_records(self) -> None:
        fake = AsyncMock(return_value=self._result(dry_run=True))
        with patch("edit_brief.draft", fake), \
             patch("orchestrator.tools.record_delegation_decision") as rec:
            out, delegations = _run_tool(
                lambda: tools.edit_brief_discover.ainvoke({"script_path": "seed/script.md"})
            )

        fake.assert_awaited_once()
        # The free op runs in dry-run mode and passes NO budget (it spends nothing).
        assert fake.await_args.kwargs == {"dry_run": True}
        assert delegations == 1
        assert rec.call_args.kwargs["collection"] == "edit_brief"
        assert "Discovery (dry-run)" in out
        assert "project_id=script-draft" in out
        assert "⚠ No voiceover takes" in out

    def test_edit_brief_draft_uses_child_budget_and_records(self) -> None:
        fake = AsyncMock(return_value=self._result(dry_run=False, cost=0.04))
        with patch("edit_brief.draft", fake), \
             patch("orchestrator.tools.record_delegation_decision") as rec:
            out, delegations = _run_tool(
                lambda: tools.edit_brief_draft.ainvoke({"script_path": "seed/script.md"})
            )

        fake.assert_awaited_once()
        _assert_child_budget(fake.await_args.kwargs["budget"])
        assert delegations == 1
        assert rec.call_args.kwargs["collection"] == "edit_brief"
        assert "status=completed" in out
        assert "brief: script-draft.edit-brief.md" in out

    def test_edit_brief_draft_failure_returns_message_not_raises(self) -> None:
        fake = AsyncMock(side_effect=RuntimeError("ffprobe missing"))
        with patch("edit_brief.draft", fake):
            out, _ = _run_tool(
                lambda: tools.edit_brief_draft.ainvoke({"script_path": "x.md"})
            )
        assert "edit-brief draft failed" in out


# ── feedback-iteration (stateless) ──────────────────────────────────────────────


class TestFeedbackIterationTools:
    def _inspect_result(self) -> MagicMock:
        return MagicMock(
            project_id="script-draft",
            section_ids=["opening-image", "close"],
            feedback_items=["tighten the calm underneath by 2 seconds", "the drop feels too slow"],
            version_from=1,
            version_to=2,
            validation_findings=[],
            snapshot_path="versions/script-draft.edit-brief.v1.md",
        )

    def _revise_result(self, *, cost: float) -> MagicMock:
        return MagicMock(
            status="completed",
            cost_usd=cost,
            version_from=1,
            version_to=2,
            brief_path="script-draft.edit-brief.md",
            snapshot_path="versions/script-draft.edit-brief.v1.md",
            applied=['"tighten the calm underneath by 2 seconds" → #the-calm-underneath adjust_duration'],
            unresolved=['"the drop feels too slow" — no drop anchor in this brief'],
            lesson_draft_ids=["draft-abc"],
        )

    def test_feedback_inspect_is_free_and_records(self) -> None:
        fake = AsyncMock(return_value=self._inspect_result())
        with patch("feedback_iteration.revise", fake), \
             patch("orchestrator.tools.record_delegation_decision") as rec:
            out, delegations = _run_tool(
                lambda: tools.feedback_inspect.ainvoke(
                    {"brief_path": "seed/script-draft.edit-brief.md", "feedback": "tighten the calm"}
                )
            )

        fake.assert_awaited_once()
        # The free op runs in dry-run mode and passes NO budget (it spends nothing).
        assert fake.await_args.kwargs == {"dry_run": True}
        assert "budget" not in fake.await_args.kwargs
        assert delegations == 1
        assert rec.call_args.kwargs["collection"] == "feedback_iteration"
        assert "Inspect (dry-run)" in out
        assert "project_id=script-draft" in out
        assert "version=1→2(planned)" in out
        assert "[1] the drop feels too slow" in out

    def test_feedback_revise_uses_child_budget_and_records(self) -> None:
        fake = AsyncMock(return_value=self._revise_result(cost=0.04))
        with patch("feedback_iteration.revise", fake), \
             patch("orchestrator.tools.record_delegation_decision") as rec:
            out, delegations = _run_tool(
                lambda: tools.feedback_revise.ainvoke(
                    {"brief_path": "seed/script-draft.edit-brief.md", "feedback": "tighten the calm"}
                )
            )

        fake.assert_awaited_once()
        _assert_child_budget(fake.await_args.kwargs["budget"])
        assert delegations == 1
        assert rec.call_args.kwargs["collection"] == "feedback_iteration"
        assert "status=completed" in out
        assert "version=1→2" in out
        assert "brief: script-draft.edit-brief.md" in out
        assert "snapshot: versions/script-draft.edit-brief.v1.md" in out
        assert "✗ unresolved:" in out
        assert "lesson drafts (confirm separately): draft-abc" in out

    def test_feedback_revise_failure_returns_message_not_raises(self) -> None:
        fake = AsyncMock(side_effect=RuntimeError("brief not found"))
        with patch("feedback_iteration.revise", fake):
            out, _ = _run_tool(
                lambda: tools.feedback_revise.ainvoke({"brief_path": "x.md", "feedback": "y"})
            )
        assert "feedback-iteration revise failed" in out


# ── graceful degrade (no crash) ────────────────────────────────────────────────


class TestSubAgentToolDegrade:
    def test_failure_returns_message_not_raises(self) -> None:
        fake = AsyncMock(side_effect=RuntimeError("agent down"))
        with patch("visual_generation.draft", fake):
            out, _ = _run_tool(lambda: tools.visual_draft.ainvoke({"intent": "x"}))
        assert "visual-generation draft failed" in out
