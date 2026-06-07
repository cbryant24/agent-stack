from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from concept_script.chains import (
    BriefParseError,
    _brief_from_data,
    _extract_json,
    _shape_system,
    generate_brief,
    shape_brief,
)


def _response(text: str, *, in_tokens: int = 100, out_tokens: int = 200) -> MagicMock:
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    msg.usage = MagicMock(input_tokens=in_tokens, output_tokens=out_tokens)
    return msg


def _client(text: str) -> MagicMock:
    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(return_value=_response(text))
    return client


# ── parsing helpers ─────────────────────────────────────────────────────────

def test_extract_json_plain() -> None:
    assert _extract_json(_response('{"a": 1}')) == {"a": 1}


def test_extract_json_fenced() -> None:
    fenced = "```json\n{\"a\": 1}\n```"
    assert _extract_json(_response(fenced)) == {"a": 1}


def test_extract_json_invalid_raises() -> None:
    with pytest.raises(BriefParseError):
        _extract_json(_response("not json"))


def test_brief_from_data_requires_sections() -> None:
    with pytest.raises(BriefParseError):
        _brief_from_data({"logline": "x", "sections": []})


def test_brief_from_data_drops_incomplete_sections() -> None:
    brief = _brief_from_data(
        {
            "logline": "x",
            "sections": [
                {"heading": "Keep", "prose": "real prose"},
                {"heading": "", "prose": "no heading"},
                {"heading": "No prose", "prose": ""},
            ],
        }
    )
    assert [s.heading for s in brief.sections] == ["Keep"]


def test_brief_from_data_music_hint_null() -> None:
    brief = _brief_from_data(
        {"logline": "x", "music_hint": None, "sections": [{"heading": "A", "prose": "p"}]}
    )
    assert brief.music_hint is None


# ── chains end to end (client mocked) ───────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_brief_parses() -> None:
    payload = json.dumps(
        {
            "logline": "A tiny film about focus.",
            "music_hint": "ambient",
            "sections": [{"heading": "Open", "prose": "[calm] Breathe."}],
        }
    )
    brief = await generate_brief("focus, calm, ~2min", _client(payload))
    assert brief.logline == "A tiny film about focus."
    assert brief.music_hint == "ambient"
    assert brief.sections[0].heading == "Open"
    assert "[calm]" in brief.sections[0].prose


@pytest.mark.asyncio
async def test_generate_brief_passes_prior_script() -> None:
    payload = json.dumps({"logline": "x", "sections": [{"heading": "A", "prose": "p"}]})
    client = _client(payload)
    await generate_brief("seeds", client, prior_script="# Old\nold prose")
    sent = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Prior script" in sent
    assert "old prose" in sent


@pytest.mark.asyncio
async def test_shape_brief_captures_cuts() -> None:
    payload = json.dumps(
        {
            "logline": "Unfiltered take on shipping.",
            "music_hint": None,
            "sections": [{"heading": "Rant", "prose": "[wry] You know what, I was wrong about that."}],
            "cuts": ["Deleted the closing pricing tangent"],
        }
    )
    brief = await shape_brief("um, so, like, shipping... director note, delete that last bit", _client(payload))
    assert brief.cut_trailer == ["Deleted the closing pricing tangent"]
    # A kept self-correction stays in the prose (authentic texture).
    assert "I was wrong about that" in brief.sections[0].prose


# ── self-correction handling: preserve (default) vs --clean ─────────────────

def test_shape_system_preserve_is_default() -> None:
    sys = _shape_system(False)
    assert "KEEP every natural stumble and self-correction VERBATIM" in sys
    assert "reproduce BOTH" in sys
    assert "RESOLVE self-corrections" not in sys


def test_shape_system_clean_resolves() -> None:
    sys = _shape_system(True)
    assert "RESOLVE self-corrections" in sys
    assert "keep ONLY the corrected version" in sys
    assert "KEEP every natural stumble and self-correction VERBATIM" not in sys


def test_shape_system_categories_1_3_4_identical() -> None:
    # Disfluency stripping, the director-note wake-phrase rule, the cuts mandate,
    # and sectioning are identical in both modes — only rule 3 swaps.
    preserve, clean = _shape_system(False), _shape_system(True)
    for fragment in (
        "STRIP disfluencies",
        "WAKE PHRASE",
        "REMOVE the wake phrase",
        "`cuts` MUST contain",
        "NEVER leave",
        "Apply sectioning",
    ):
        assert fragment in preserve, fragment
        assert fragment in clean, fragment


@pytest.mark.asyncio
async def test_shape_brief_clean_flag_selects_prompt() -> None:
    payload = json.dumps({"logline": "x", "sections": [{"heading": "A", "prose": "p"}]})

    client = _client(payload)
    await shape_brief("transcript", client, clean=True)
    assert "RESOLVE self-corrections" in client.messages.create.call_args.kwargs["system"]

    default_client = _client(payload)
    await shape_brief("transcript", default_client)  # default = preserve
    assert "KEEP every natural stumble" in default_client.messages.create.call_args.kwargs["system"]


# ── cut-trailer safety net ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_shape_brief_warns_when_wake_phrase_has_no_cut(caplog) -> None:
    payload = json.dumps(
        {"logline": "x", "sections": [{"heading": "A", "prose": "p"}], "cuts": []}
    )
    with caplog.at_level(logging.WARNING, logger="concept_script.chains"):
        await shape_brief("um, director note remove every young descriptor", _client(payload))
    assert any("wake phrase" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_shape_brief_no_warning_without_wake_phrase(caplog) -> None:
    payload = json.dumps(
        {"logline": "x", "sections": [{"heading": "A", "prose": "p"}], "cuts": []}
    )
    with caplog.at_level(logging.WARNING, logger="concept_script.chains"):
        await shape_brief("um, so like, shipping is hard", _client(payload))
    assert not any("wake phrase" in r.getMessage() for r in caplog.records)
