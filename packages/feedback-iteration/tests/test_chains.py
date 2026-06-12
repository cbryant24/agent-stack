from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from feedback_iteration.chains import map_and_diagnose
from feedback_iteration.models import FeedbackItem
from feedback_iteration.parser import parse_brief
from feedback_iteration.retrieval import RetrievedContext


def _msg(text: str):
    return SimpleNamespace(
        content=[SimpleNamespace(text=text)],
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )


def _client(*texts: str):
    c = MagicMock()
    c.messages.create = AsyncMock(side_effect=[_msg(t) for t in texts])
    return c


def _parsed(real_brief_text):
    return parse_brief(real_brief_text, "x")


def _feedback(*texts: str):
    return [FeedbackItem(index=i, text=t) for i, t in enumerate(texts)]


@pytest.mark.asyncio
async def test_user_message_carries_sections_and_feedback(real_brief_text, monkeypatch):
    captured = {}

    async def _create(**kwargs):
        captured.update(kwargs)
        return _msg('{"items": [], "overall_notations": []}')

    client = MagicMock()
    client.messages.create = _create
    await map_and_diagnose(
        _parsed(real_brief_text), _feedback("the calm section drags"), RetrievedContext(), client
    )
    user = captured["messages"][0]["content"]
    assert "the calm section drags" in user
    assert "#the-calm-underneath" in user
    assert "40.700s" in user  # current timing handed as fixed facts


@pytest.mark.asyncio
async def test_time_shift_parses_with_quote_and_no_timestamp(real_brief_text):
    payload = {
        "items": [
            {
                "feedback_index": 0,
                "change_type": "time_shift",
                "resolved_anchor": "the-calm-underneath",
                "diagnosis": "drags",
                "time_shift": {
                    "op": "adjust_duration",
                    "magnitude_sec": 2.0,
                    "magnitude_source_quote": "tighten by 2 seconds",
                    "direction": "shorter",
                },
            }
        ],
        "overall_notations": [],
    }
    client = _client(json.dumps(payload))
    res = await map_and_diagnose(
        _parsed(real_brief_text), _feedback("tighten by 2 seconds"), RetrievedContext(), client
    )
    item = res.items[0]
    assert item.change_type == "time_shift"
    assert item.time_shift.magnitude_sec == 2.0
    assert item.time_shift.magnitude_source_quote == "tighten by 2 seconds"
    # there is no field for a resulting timestamp anywhere in the spec
    assert not hasattr(item.time_shift, "new_start")


@pytest.mark.asyncio
async def test_unresolved_has_no_anchor(real_brief_text):
    payload = {
        "items": [
            {
                "feedback_index": 0,
                "change_type": "unresolved",
                "resolved_anchor": None,
                "diagnosis": "there is no drop in this brief",
            }
        ],
        "overall_notations": [],
    }
    client = _client(json.dumps(payload))
    res = await map_and_diagnose(
        _parsed(real_brief_text), _feedback("the drop feels too slow"), RetrievedContext(), client
    )
    assert res.items[0].resolved_anchor is None
    assert res.items[0].change_type == "unresolved"


@pytest.mark.asyncio
async def test_bad_json_retries_once_then_parses(real_brief_text):
    good = '{"items": [], "overall_notations": ["ok"]}'
    client = _client("not json at all", good)
    res = await map_and_diagnose(
        _parsed(real_brief_text), _feedback("x"), RetrievedContext(), client
    )
    assert res.overall_notations == ["ok"]
    assert client.messages.create.await_count == 2


@pytest.mark.asyncio
async def test_fenced_json_tolerated(real_brief_text):
    fenced = '```json\n{"items": [], "overall_notations": ["fenced"]}\n```'
    client = _client(fenced)
    res = await map_and_diagnose(
        _parsed(real_brief_text), _feedback("x"), RetrievedContext(), client
    )
    assert res.overall_notations == ["fenced"]
    assert client.messages.create.await_count == 1
