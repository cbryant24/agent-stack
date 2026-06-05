from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voiceover_direction.directed_script import read_directed_script
from voiceover_direction.models import DirectedSection
from voiceover_direction.retrieval import RetrievedContext


def _mock_stores() -> tuple[MagicMock, MagicMock, MagicMock]:
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.list_voices = MagicMock(return_value=[])
    store.search_takes = AsyncMock(return_value=[])
    store.search_lessons = AsyncMock(return_value=[])
    memory = MagicMock()
    knowledge = MagicMock()
    return store, memory, knowledge


def _directed_sections() -> list[DirectedSection]:
    return [
        DirectedSection(section_id="intro", heading="Intro", text="[warm] Welcome.",
                        voice_id=None, model="eleven_v3", settings={}, notes="soft"),
        DirectedSection(section_id="body", heading="Body", text="The point. [pause]",
                        voice_id=None, model="eleven_v3", settings={}, notes="land it"),
    ]


def _write_script(tmp_path: Path) -> Path:
    p = tmp_path / "ep.md"
    p.write_text("# Intro\nWelcome.\n\n# Body\nThe point.\n", encoding="utf-8")
    return p


@pytest.mark.asyncio
async def test_direct_end_to_end_writes_file(tmp_path: Path) -> None:
    from voiceover_direction.agent import direct

    script = _write_script(tmp_path)
    with (
        patch("voiceover_direction.agent._get_stores", return_value=_mock_stores()),
        patch("voiceover_direction.agent.AsyncAnthropic", return_value=MagicMock()),
        patch("voiceover_direction.agent.retrieve_context", AsyncMock(return_value=RetrievedContext())),
        patch("voiceover_direction.agent.direct_script",
              AsyncMock(return_value=(_directed_sections(), "soft to assured"))),
        patch("voiceover_direction.agent.render_run_report", return_value=Path("/tmp/r.md")),
        patch("voiceover_direction.agent.notify_run_complete"),
    ):
        result = await direct(script)

    assert result.status == "completed"
    assert result.items_processed == 1
    assert result.overall_reasoning == "soft to assured"
    assert [s.section_id for s in result.directed_script.sections] == ["intro", "body"]

    # File written next to the input, and re-reads into an equal DirectedScript.
    assert result.output_path == tmp_path / "ep.directed.md"
    assert result.output_path.exists()
    assert read_directed_script(result.output_path) == result.directed_script


@pytest.mark.asyncio
async def test_dry_run_writes_no_file(tmp_path: Path) -> None:
    from voiceover_direction.agent import direct

    script = _write_script(tmp_path)
    chain = AsyncMock(return_value=(_directed_sections(), "x"))
    with (
        patch("voiceover_direction.agent._get_stores", return_value=_mock_stores()),
        patch("voiceover_direction.agent.AsyncAnthropic", return_value=MagicMock()),
        patch("voiceover_direction.agent.retrieve_context", AsyncMock(return_value=RetrievedContext())),
        patch("voiceover_direction.agent.direct_script", chain),
        patch("voiceover_direction.agent.render_run_report", return_value=Path("/tmp/r.md")),
        patch("voiceover_direction.agent.notify_run_complete"),
    ):
        result = await direct(script, dry_run=True)

    chain.assert_not_awaited()  # no LLM call on dry run
    assert result.output_path is None
    assert not (tmp_path / "ep.directed.md").exists()
    assert result.items_processed == 0


@pytest.mark.asyncio
async def test_custom_output_path_and_project_id(tmp_path: Path) -> None:
    from voiceover_direction.agent import direct

    script = _write_script(tmp_path)
    out = tmp_path / "custom.md"
    with (
        patch("voiceover_direction.agent._get_stores", return_value=_mock_stores()),
        patch("voiceover_direction.agent.AsyncAnthropic", return_value=MagicMock()),
        patch("voiceover_direction.agent.retrieve_context", AsyncMock(return_value=RetrievedContext())),
        patch("voiceover_direction.agent.direct_script",
              AsyncMock(return_value=(_directed_sections(), "x"))),
        patch("voiceover_direction.agent.render_run_report", return_value=None),
        patch("voiceover_direction.agent.notify_run_complete"),
    ):
        result = await direct(script, output_path=out, project_id="myproj", domain="tech")

    assert result.output_path == out
    assert out.exists()
    assert result.directed_script.project_id == "myproj"
    assert result.directed_script.domain == "tech"
