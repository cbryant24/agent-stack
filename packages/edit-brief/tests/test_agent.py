from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from edit_brief import agent
from edit_brief.models import DiscoveredInputs, DiscoveredMusic, SectionSteps
from edit_brief.retrieval import Finding, RetrievedContext

SCRIPT = """Music: ambient piano

# Intro
[quiet] Ten words here to make a clean estimate count yes now.

# Outro
Five more words right here.
"""


def _write_script(tmp_path: Path) -> Path:
    p = tmp_path / "myproj.md"
    p.write_text(SCRIPT)
    return p


def _patch_common(monkeypatch, inputs, ctx):
    monkeypatch.setattr(agent, "get_memory_store", lambda: MagicMock())
    monkeypatch.setattr(agent, "UserKnowledgeStore", lambda store: MagicMock())
    monkeypatch.setattr(agent, "discover_inputs", AsyncMock(return_value=inputs))
    monkeypatch.setattr(agent, "retrieve_context", AsyncMock(return_value=ctx))


@pytest.mark.asyncio
async def test_dry_run_computes_timeline_writes_nothing(tmp_path, monkeypatch):
    script = _write_script(tmp_path)
    inputs = DiscoveredInputs(project_id="myproj", music=DiscoveredMusic())
    _patch_common(monkeypatch, inputs, RetrievedContext())
    # synthesis must NOT be called on a dry run
    monkeypatch.setattr(agent, "synthesize_sections",
                        AsyncMock(side_effect=AssertionError("LLM called on dry run")))

    result = await agent.draft(script, dry_run=True)

    assert result.dry_run is True
    assert result.brief_path is None
    assert len(result.brief.timeline) == 2
    assert all(r.timing_source == "estimate" for r in result.brief.timeline)
    # no edit-brief.md written next to the script
    assert not (tmp_path / "myproj.edit-brief.md").exists()


@pytest.mark.asyncio
async def test_full_run_writes_brief_and_finalizes(tmp_path, monkeypatch):
    script = _write_script(tmp_path)
    inputs = DiscoveredInputs(project_id="myproj", music=DiscoveredMusic())
    _patch_common(monkeypatch, inputs, RetrievedContext(findings=[Finding("J-cut", "audio leads")]))
    monkeypatch.setattr(
        agent, "synthesize_sections",
        AsyncMock(return_value=(
            [SectionSteps(section_id="intro", heading="x", steps=["do a thing"]),
             SectionSteps(section_id="outro", heading="y", steps=["do another"])],
            ["overall note"],
        )),
    )
    monkeypatch.setattr(agent, "AsyncAnthropic", lambda **kw: MagicMock())
    monkeypatch.setattr(agent, "render_run_report", lambda run_id, name: None)
    monkeypatch.setattr(agent, "notify_run_complete", lambda *a, **k: None)

    result = await agent.draft(script)

    assert result.status == "completed"
    out = tmp_path / "myproj.edit-brief.md"
    assert out.exists()
    md = out.read_text()
    assert "- [ ] do a thing" in md
    assert "overall note" in result.brief.notations
    assert result.brief_path == out


@pytest.mark.asyncio
async def test_no_headings_returns_early(tmp_path, monkeypatch):
    script = tmp_path / "empty.md"
    script.write_text("just prose, no headings at all")
    inputs = DiscoveredInputs(project_id="empty", music=DiscoveredMusic())
    _patch_common(monkeypatch, inputs, RetrievedContext())
    monkeypatch.setattr(agent, "synthesize_sections",
                        AsyncMock(side_effect=AssertionError("should not synthesize")))

    result = await agent.draft(script)
    assert result.brief.timeline == []
    assert any("no markdown headings" in n.lower() for n in result.brief.notations)


def test_project_id_defaults_to_script_stem(tmp_path, monkeypatch):
    script = _write_script(tmp_path)
    captured = {}

    async def fake_discover(store, *, project_id, **kw):
        captured["pid"] = project_id
        return DiscoveredInputs(project_id=project_id, music=DiscoveredMusic())

    monkeypatch.setattr(agent, "get_memory_store", lambda: MagicMock())
    monkeypatch.setattr(agent, "UserKnowledgeStore", lambda store: MagicMock())
    monkeypatch.setattr(agent, "discover_inputs", fake_discover)
    monkeypatch.setattr(agent, "retrieve_context", AsyncMock(return_value=RetrievedContext()))

    agent.draft_sync(script, dry_run=True)
    assert captured["pid"] == "myproj"
