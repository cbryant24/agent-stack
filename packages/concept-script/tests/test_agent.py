from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from concept_script.agent import draft, shape
from concept_script.serialize import from_script_md


def _response(text: str) -> MagicMock:
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    msg.usage = MagicMock(input_tokens=120, output_tokens=300)
    return msg


def _patches(payload: str):
    """Patch the Anthropic client + reporting side effects for an agent run."""
    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(return_value=_response(payload))
    return (
        patch("concept_script.agent.AsyncAnthropic", return_value=client),
        patch("concept_script.agent.render_run_report", return_value=Path("/tmp/report.md")),
        patch("concept_script.agent.notify_run_complete"),
    )


@pytest.mark.asyncio
async def test_draft_writes_script(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "logline": "A film about focus.",
            "music_hint": "ambient",
            "sections": [{"heading": "Open", "prose": "[calm] Breathe."}],
        }
    )
    out = tmp_path / "script.md"
    p_client, p_report, p_notify = _patches(payload)
    with p_client, p_report, p_notify:
        result = await draft("focus, ~2min", output=out)

    assert result.status == "completed"
    assert result.cost_usd > 0
    assert out.exists()
    written = from_script_md(out.read_text())
    assert written.logline == "A film about focus."
    assert written.sections[0].heading == "Open"


@pytest.mark.asyncio
async def test_draft_dry_run_writes_nothing(tmp_path: Path) -> None:
    out = tmp_path / "script.md"
    # client should never be called on dry-run, but patch anyway
    p_client, p_report, p_notify = _patches("{}")
    with p_client as mock_anthropic, p_report, p_notify:
        result = await draft("seeds", output=out, dry_run=True)

    assert result.status == "completed"
    assert not out.exists()
    assert mock_anthropic.return_value.messages.create.await_count == 0


@pytest.mark.asyncio
async def test_shape_writes_cut_trailer(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "logline": "Raw take.",
            "sections": [{"heading": "Rant", "prose": "[wry] Shipping is hard."}],
            "cuts": ["Deleted the closing tangent"],
        }
    )
    out = tmp_path / "shaped.md"
    p_client, p_report, p_notify = _patches(payload)
    with p_client, p_report, p_notify:
        result = await shape("um director note delete the end", output=out)

    assert result.brief.cut_trailer == ["Deleted the closing tangent"]
    assert "director note cuts applied" in out.read_text()


@pytest.mark.asyncio
async def test_shape_clean_reaches_chain_with_clean_prompt(tmp_path: Path) -> None:
    payload = json.dumps(
        {"logline": "x", "sections": [{"heading": "A", "prose": "p"}], "cuts": []}
    )
    p_client, p_report, p_notify = _patches(payload)
    with p_client as mock_anthropic, p_report, p_notify:
        await shape("director note tidy this up", clean=True, output=tmp_path / "s.md")
    system = mock_anthropic.return_value.messages.create.call_args.kwargs["system"]
    assert "RESOLVE self-corrections" in system


@pytest.mark.asyncio
async def test_shape_default_uses_preserve_prompt(tmp_path: Path) -> None:
    payload = json.dumps(
        {"logline": "x", "sections": [{"heading": "A", "prose": "p"}]}
    )
    p_client, p_report, p_notify = _patches(payload)
    with p_client as mock_anthropic, p_report, p_notify:
        await shape("a transcript", output=tmp_path / "s.md")
    system = mock_anthropic.return_value.messages.create.call_args.kwargs["system"]
    assert "KEEP every natural stumble" in system
