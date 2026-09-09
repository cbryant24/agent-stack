from __future__ import annotations

import json
from pathlib import Path

import pytest

from video_clipping.decide import decide_segment
from video_clipping.exceptions import DecisionParseError
from video_clipping.models import Segment, Spec

from tests.fakes import FakeCompletion, FakeProvider


def _spec(tmp_path: Path) -> Spec:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    return Spec(
        video=video,
        location="Yosemite — Half Dome",
        event_type="hike",
        target_clip_length_sec=(15.0, 60.0),
        max_total_output_min=5.0,
        content_wanted=["landscape and summit views", "wildlife"],
        exclude_when=["low_video_quality", "theme_mismatch"],
        tone_notes="calm and observational",
    )


def _seg() -> Segment:
    seg = Segment(segment_id="seg-alpha", start=10.0, end=42.0, duration=32.0)
    seg.transcript = "the wind is picking up"
    seg.visual_summary = "wide shot of a granite dome"
    return seg


@pytest.mark.asyncio
async def test_decide_segment_happy_path(tmp_path: Path) -> None:
    canned = {
        "action": "include",
        "refined_start": 12.0,
        "refined_end": 38.0,
        "exclude_reason": None,
        "theme_match": 0.9,
        "confidence": 0.85,
        "one_line_summary": "wide granite summit view with wind",
    }
    provider = FakeProvider(responses=[FakeCompletion(text=json.dumps(canned))])
    spec = _spec(tmp_path)
    seg = _seg()
    prior = ["switchbacks up the wooded slope", "wildflowers on the granite ledge"]

    decision = await decide_segment(provider, spec, seg, prior)

    assert decision.segment_id == "seg-alpha"
    assert decision.action == "include"
    assert decision.refined_start == 12.0
    assert decision.theme_match == 0.9

    assert len(provider.calls) == 1
    user = provider.calls[0]["user_text"]
    # Prior accepted summaries are threaded through the user prompt.
    for s in prior:
        assert s in user
    # Segment context is embedded, not just the id.
    assert "seg-alpha" in user
    assert "wide shot of a granite dome" in user
    # Spec context is embedded.
    assert "Yosemite" in user
    assert "calm and observational" in user
    # System prompt spells out the JSON schema and the spec-narrowed exclude set.
    system = provider.calls[0]["system"]
    assert "action" in system
    assert '"low_video_quality"' in system
    assert '"theme_mismatch"' in system
    # Spec did not include "unidentifiable", so it shouldn't appear.
    assert '"unidentifiable"' not in system


@pytest.mark.asyncio
async def test_decide_segment_strips_code_fence(tmp_path: Path) -> None:
    payload = {
        "action": "exclude", "refined_start": 10.0, "refined_end": 42.0,
        "exclude_reason": "theme_mismatch", "theme_match": 0.2, "confidence": 0.7,
        "one_line_summary": "car park with no view",
    }
    provider = FakeProvider(responses=[
        FakeCompletion(text=f"```json\n{json.dumps(payload)}\n```")
    ])
    decision = await decide_segment(provider, _spec(tmp_path), _seg(), [])
    assert decision.action == "exclude"
    assert decision.exclude_reason == "theme_mismatch"


@pytest.mark.asyncio
async def test_decide_segment_retries_on_bad_json(tmp_path: Path) -> None:
    good = {
        "action": "trim", "refined_start": 15.0, "refined_end": 40.0,
        "exclude_reason": None, "theme_match": 0.7, "confidence": 0.6,
        "one_line_summary": "tightened summit pan",
    }
    provider = FakeProvider(responses=[
        FakeCompletion(text="totally not json"),
        FakeCompletion(text=json.dumps(good)),
    ])
    decision = await decide_segment(provider, _spec(tmp_path), _seg(), [])
    assert decision.action == "trim"
    assert len(provider.calls) == 2
    # Retry adds the reminder suffix.
    assert "STRICT JSON" in provider.calls[0]["system"] or "STRICT JSON" in provider.calls[1]["system"]
    assert "did not parse as valid JSON" in provider.calls[1]["user_text"]


@pytest.mark.asyncio
async def test_decide_segment_injects_prior_lessons_block(tmp_path: Path) -> None:
    """When lessons are surfaced, they appear as a labeled block in the user prompt."""
    canned = {
        "action": "include", "refined_start": 10.0, "refined_end": 42.0,
        "exclude_reason": None, "theme_match": 0.8, "confidence": 0.9,
        "one_line_summary": "granite ridge with wind",
    }
    provider = FakeProvider(responses=[FakeCompletion(text=json.dumps(canned))])
    lessons = [
        "hike specs with 'landscape' often over-exclude on theme_mismatch — loosen wording",
        "runs on video deadbeef tend to duplicate prior run c0ffee — consider skipping",
    ]
    await decide_segment(provider, _spec(tmp_path), _seg(), [], lessons)
    user = provider.calls[0]["user_text"]
    assert "PRIOR LESSONS FOR THIS EVENT TYPE" in user
    for lesson in lessons:
        assert lesson in user


@pytest.mark.asyncio
async def test_decide_segment_omits_lessons_block_when_empty(tmp_path: Path) -> None:
    canned = {
        "action": "include", "refined_start": 10.0, "refined_end": 42.0,
        "exclude_reason": None, "theme_match": 0.8, "confidence": 0.9,
        "one_line_summary": "granite ridge with wind",
    }
    provider = FakeProvider(responses=[FakeCompletion(text=json.dumps(canned))])
    await decide_segment(provider, _spec(tmp_path), _seg(), [])
    user = provider.calls[0]["user_text"]
    assert "PRIOR LESSONS FOR THIS EVENT TYPE" not in user


@pytest.mark.asyncio
async def test_decide_segment_raises_after_second_bad_json(tmp_path: Path) -> None:
    provider = FakeProvider(responses=[
        FakeCompletion(text="junk"),
        FakeCompletion(text="still junk"),
    ])
    with pytest.raises(DecisionParseError):
        await decide_segment(provider, _spec(tmp_path), _seg(), [])
    assert len(provider.calls) == 2
