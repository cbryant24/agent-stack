from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from feedback_iteration import agent
from feedback_iteration.models import (
    LessonCandidate,
    MappedItem,
    MappingResult,
    StepRewriteSpec,
    TimeShiftSpec,
)
from feedback_iteration.retrieval import RetrievedContext

FEEDBACK = (
    "tighten the calm underneath by 2 seconds\n"
    "the close fade should be 2s not 1s\n"
    "I always want calm sections tighter\n"
    "the drop feels too slow"
)


def _write_brief(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "script-draft.edit-brief.md"
    p.write_text(text, encoding="utf-8")
    return p


@pytest.mark.asyncio
async def test_dry_run_echoes_and_writes_nothing(tmp_path, real_brief_text, monkeypatch):
    p = _write_brief(tmp_path, real_brief_text)
    monkeypatch.setattr(agent, "map_and_diagnose", AsyncMock(side_effect=AssertionError("LLM called on dry run")))
    monkeypatch.setattr(agent, "retrieve_context", AsyncMock(side_effect=AssertionError("retrieval on dry run")))

    result = await agent.revise(p, FEEDBACK, dry_run=True)

    assert result.dry_run is True
    assert result.feedback_items == [
        "tighten the calm underneath by 2 seconds",
        "the close fade should be 2s not 1s",
        "I always want calm sections tighter",
        "the drop feels too slow",
    ]
    assert result.version_from == 1 and result.version_to == 2
    assert p.read_text(encoding="utf-8") == real_brief_text  # untouched
    assert not (tmp_path / "versions").exists()  # no snapshot written


def _full_run_mapping() -> MappingResult:
    return MappingResult(
        items=[
            MappedItem(
                feedback_index=0,
                change_type="time_shift",
                resolved_anchor="the-calm-underneath",
                diagnosis="the calm section drags",
                time_shift=TimeShiftSpec(
                    op="adjust_duration",
                    magnitude_sec=2.0,
                    magnitude_source_quote="by 2 seconds",
                    direction="shorter",
                ),
            ),
            MappedItem(
                feedback_index=1,
                change_type="step_rewrite",
                resolved_anchor="close",
                diagnosis="fade duration tweak",
                step_rewrite=StepRewriteSpec(
                    target_step_number=8,
                    # Authored against the PRE-cascade numbers: close ends at
                    # 96.200s before the upstream tighten. The cascade must retime
                    # this stale token to 94.200s.
                    new_text="Add a 2.0s Dip to Color Dissolve (black) ending at 96.200s (free).",
                ),
            ),
            MappedItem(
                feedback_index=2,
                change_type="lesson_only",
                resolved_anchor=None,
                diagnosis="durable taste rule",
                lesson_candidate=LessonCandidate(statement="Calm sections should breathe less.", confidence="medium"),
            ),
            MappedItem(
                feedback_index=3,
                change_type="unresolved",
                resolved_anchor=None,
                diagnosis="there is no drop / music in this brief",
            ),
        ],
        overall_notations=[],
    )


@pytest.fixture
def _patch_full_run(monkeypatch):
    uks = MagicMock()
    uks.propose_entry = AsyncMock(return_value=SimpleNamespace(draft_id="draft-xyz"))
    uks.confirm_entry = AsyncMock()
    monkeypatch.setattr(agent, "get_memory_store", lambda: MagicMock())
    monkeypatch.setattr(agent, "UserKnowledgeStore", lambda *a, **k: uks)
    monkeypatch.setattr(agent, "retrieve_context", AsyncMock(return_value=RetrievedContext()))
    monkeypatch.setattr(agent, "AsyncAnthropic", lambda **k: MagicMock())
    monkeypatch.setattr(agent, "map_and_diagnose", AsyncMock(return_value=_full_run_mapping()))
    monkeypatch.setattr(agent, "render_run_report", lambda *a, **k: Path("/tmp/report.md"))
    monkeypatch.setattr(agent, "notify_run_complete", lambda *a, **k: None)
    return uks


@pytest.mark.asyncio
async def test_full_run_patches_in_place_preserving_state(tmp_path, real_brief_text, _patch_full_run):
    # Simulate a director-checked step in the close section to exercise invalidation.
    checked = real_brief_text.replace(
        "- [ ] 8. For a clean out", "- [x] 8. For a clean out", 1
    )
    p = _write_brief(tmp_path, checked)

    result = await agent.revise(p, FEEDBACK)
    out = p.read_text(encoding="utf-8")

    # snapshot taken verbatim before the patch
    snap = tmp_path / "versions" / "script-draft.edit-brief.v1.md"
    assert snap.exists() and snap.read_text(encoding="utf-8") == checked

    # frontmatter bumped
    assert "version: 2" in out and "version: 1" not in out

    # the resized section's end retimed (57.500 → 55.500), authoritative surfaces
    assert "### The calm underneath — 00:40.700 → 00:55.500" in out
    assert "| [The calm underneath](#the-calm-underneath) | 00:40.700 | 00:55.500 |" in out

    # downstream sections shifted -2.0 on both table and heading and prose
    assert "### A different way to work — 00:56.000 → 01:11.200" in out
    assert "move the playhead to 56.000s" in out

    # the close step 8 was rewritten AND unchecked (director state invalidated)
    assert "- [ ] 8. Add a 2.0s Dip to Color Dissolve" in out
    # the rewrite's stale timestamp was retimed by the cascade (96.200 → 94.200)
    assert "ending at 94.200s" in out and "ending at 96.200s" not in out
    assert result.invalidated_checks and "step 8 was checked" in result.invalidated_checks[0]

    # upstream-unchanged section is byte-identical (no spurious edits)
    assert "### Opening image — 00:00.000 → 00:08.400" in out
    assert "### The problem we don't name — 00:08.900 → 00:24.100" in out

    # the unmappable item surfaced unapplied + named in the version log
    assert any("the drop feels too slow" in u for u in result.unresolved)
    assert "## Version log" in out and "### v2" in out
    assert "Unresolved (unapplied)" in out

    # a durable lesson was PROPOSED (not confirmed)
    assert result.lesson_draft_ids == ["draft-xyz"]
    _patch_full_run.confirm_entry.assert_not_awaited()

    assert result.version_from == 1 and result.version_to == 2
    assert result.status == "completed"


@pytest.mark.asyncio
async def test_numberless_timing_request_demotes_to_unresolved(tmp_path, real_brief_text, monkeypatch):
    mapping = MappingResult(
        items=[
            MappedItem(
                feedback_index=0,
                change_type="time_shift",
                resolved_anchor="the-calm-underneath",
                diagnosis="drags",
                time_shift=TimeShiftSpec(
                    op="adjust_duration",
                    magnitude_sec=2.0,
                    magnitude_source_quote="shave a couple seconds",  # no digit
                    direction="shorter",
                ),
            )
        ]
    )
    uks = MagicMock()
    uks.propose_entry = AsyncMock(return_value=SimpleNamespace(draft_id="d"))
    monkeypatch.setattr(agent, "get_memory_store", lambda: MagicMock())
    monkeypatch.setattr(agent, "UserKnowledgeStore", lambda *a, **k: uks)
    monkeypatch.setattr(agent, "retrieve_context", AsyncMock(return_value=RetrievedContext()))
    monkeypatch.setattr(agent, "AsyncAnthropic", lambda **k: MagicMock())
    monkeypatch.setattr(agent, "map_and_diagnose", AsyncMock(return_value=mapping))
    monkeypatch.setattr(agent, "render_run_report", lambda *a, **k: None)
    monkeypatch.setattr(agent, "notify_run_complete", lambda *a, **k: None)

    p = _write_brief(tmp_path, real_brief_text)
    result = await agent.revise(p, "shave a couple seconds off the calm section")
    out = p.read_text(encoding="utf-8")

    assert any("no stated amount" in u for u in result.unresolved)
    # no retime happened — the calm end is unchanged
    assert "### The calm underneath — 00:40.700 → 00:57.500" in out
