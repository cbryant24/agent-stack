from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from feedback_iteration.lessons import propose_lessons
from feedback_iteration.models import LessonCandidate


@pytest.mark.asyncio
async def test_propose_lessons_proposes_only_with_provenance():
    uks = MagicMock()
    uks.propose_entry = AsyncMock(return_value=SimpleNamespace(draft_id="draft-1"))
    uks.confirm_entry = AsyncMock()

    ids = await propose_lessons(
        uks,
        [LessonCandidate(statement="VO should duck under music in every mix", confidence="medium")],
        source_ref="script-draft:script-draft.edit-brief.md",
        feedback_verbatim=["the VO competes with the music"],
    )

    assert ids == ["draft-1"]
    uks.confirm_entry.assert_not_awaited()  # propose-only; the director gates confirm
    _, kwargs = uks.propose_entry.call_args
    assert kwargs["domain"] == "editing_preference"
    assert kwargs["source_type"] == "feedback"
    assert kwargs["source_ref"] == "script-draft:script-draft.edit-brief.md"
    assert kwargs["examples"] == ["the VO competes with the music"]


@pytest.mark.asyncio
async def test_lesson_failure_does_not_raise():
    uks = MagicMock()
    uks.propose_entry = AsyncMock(side_effect=RuntimeError("qdrant down"))
    ids = await propose_lessons(
        uks, [LessonCandidate(statement="x")], source_ref="r", feedback_verbatim=["f"]
    )
    assert ids == []
