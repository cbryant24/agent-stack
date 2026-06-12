from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from edit_brief.chains import _build_user_message, synthesize_sections
from edit_brief.models import BeatGrid, BeatProposal, TimelineRow
from edit_brief.retrieval import Finding, RetrievedContext


def _msg(text: str):
    return SimpleNamespace(
        content=[SimpleNamespace(text=text)],
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )


def _client(text: str):
    c = MagicMock()
    c.messages.create = AsyncMock(return_value=_msg(text))
    return c


TIMELINE = [
    TimelineRow(section_id="intro", heading="Intro", start_sec=0.0, end_sec=3.0,
                vo_file="intro.mp3", timing_source="vo"),
    TimelineRow(section_id="outro", heading="Outro", start_sec=3.5, end_sec=8.5,
                timing_source="estimate"),
]
CTX = RetrievedContext(
    toolset=["Resolve free, no Studio NR"],
    findings=[Finding(technique="J-cut", description="audio leads", upgrade_flag="x")],
)


def test_user_message_carries_computed_numbers_and_is_never_blank():
    msg = _build_user_message("proj", TIMELINE, None, CTX, [])
    assert "0.000s → 3.000s" in msg
    assert "ESTIMATED" in msg            # the estimate marker for outro
    assert "Resolve free, no Studio NR" in msg
    assert "J-cut" in msg
    assert "no BPM available" in msg     # beat grid absent branch


def test_user_message_includes_beat_grid_when_present():
    grid = BeatGrid(bpm=120, beat_sec=0.5, bar_sec=2.0,
                    boundary_proposals=[BeatProposal(section_id="outro", boundary_sec=3.5,
                                                     nearest_beat_sec=3.5, nearest_bar_sec=4.0)])
    msg = _build_user_message("proj", TIMELINE, grid, CTX, [])
    assert "BPM 120" in msg and "nearest beat 3.500s" in msg


@pytest.mark.asyncio
async def test_synthesize_parses_steps_and_fills_headings():
    payload = {
        "sections": [
            {"section_id": "intro", "steps": ["place intro.mp3 at 0.0s"], "notations": []},
            {"section_id": "outro", "steps": ["cut on the beat"], "notations": ["estimate"]},
        ],
        "overall_notations": ["check the export codec"],
    }
    client = _client(json.dumps(payload))
    sections, overall = await synthesize_sections("proj", TIMELINE, None, CTX, [], client)
    assert [s.section_id for s in sections] == ["intro", "outro"]
    assert sections[0].heading == "Intro"          # filled from timeline, not the LLM
    assert sections[0].steps == ["place intro.mp3 at 0.0s"]
    assert overall == ["check the export codec"]


@pytest.mark.asyncio
async def test_synthesize_retries_once_on_bad_json():
    good = {"sections": [{"section_id": "intro", "steps": ["x"]},
                         {"section_id": "outro", "steps": ["y"]}]}
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=[_msg("not json at all"), _msg(json.dumps(good))])
    sections, _ = await synthesize_sections("proj", TIMELINE, None, CTX, [], client)
    assert client.messages.create.await_count == 2
    assert sections[0].steps == ["x"]


@pytest.mark.asyncio
async def test_synthesize_tolerates_fenced_json():
    payload = {"sections": [{"section_id": "intro", "steps": ["a"]},
                            {"section_id": "outro", "steps": ["b"]}]}
    client = _client("```json\n" + json.dumps(payload) + "\n```")
    sections, _ = await synthesize_sections("proj", TIMELINE, None, CTX, [], client)
    assert sections[1].steps == ["b"]
