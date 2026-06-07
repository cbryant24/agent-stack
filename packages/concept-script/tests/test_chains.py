from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from concept_script.chains import (
    BriefParseError,
    _brief_from_data,
    _extract_json,
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
