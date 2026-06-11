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


# ── graceful degrade (no crash) ────────────────────────────────────────────────


class TestSubAgentToolDegrade:
    def test_failure_returns_message_not_raises(self) -> None:
        fake = AsyncMock(side_effect=RuntimeError("agent down"))
        with patch("visual_generation.draft", fake):
            out, _ = _run_tool(lambda: tools.visual_draft.ainvoke({"intent": "x"}))
        assert "visual-generation draft failed" in out
