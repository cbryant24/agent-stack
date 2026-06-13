"""Synthetic VO-backed smoke test — the integration proof of the PRIMARY path
(decision 2B): computed-from-VO-duration timestamps + a real beat grid, live.

Opt-in only: gated behind EDIT_BRIEF_SMOKE=1 plus a reachable Qdrant, ffmpeg, and
real API keys in the repo `.env`. It NEVER runs (or charges) in the normal suite.

It generates two deterministic tones (3.0s / 5.0s), seeds two `take` points into
voiceover_direction_memory under a dedicated throwaway project, runs `draft`, and
asserts the computed timeline + beat proposals — then deletes everything it wrote.

Run it with:
    EDIT_BRIEF_SMOKE=1 uv run pytest packages/edit-brief/tests/test_smoke_fixture.py -s
"""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from .conftest import requires_ffmpeg, requires_qdrant

SMOKE = pytest.mark.skipif(
    os.environ.get("EDIT_BRIEF_SMOKE") != "1",
    reason="set EDIT_BRIEF_SMOKE=1 to run the live VO-backed smoke test",
)

PROJECT = "edit-brief-smoke"
COLLECTION = "voiceover_direction_memory"
REPO_ROOT = Path(__file__).resolve().parents[3]

FIXTURE_SCRIPT = """Music: warm analog synth pad

# Intro
This is the intro section spoken over roughly three seconds of audio.

# Outro
And this is the outro, a slightly longer five second close to the piece.
"""


def _load_real_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (REPO_ROOT / ".env").read_text().splitlines():
        m = re.match(r"^([A-Z_]+)=(.*)$", line.strip())
        if m and m.group(2):
            env[m.group(1)] = m.group(2)
    return env


@SMOKE
@requires_qdrant
@requires_ffmpeg
def test_vo_backed_fixture_computes_real_timestamps(tmp_path, monkeypatch):
    # Override the autouse fake_env with the real keys so embeddings + synthesis
    # actually run against Qdrant + Voyage + Anthropic.
    real = _load_real_env()
    if not real.get("PRODUCTION_AGENTS_ANTHROPIC_API_KEY") or not real.get("VOYAGE_API_KEY"):
        pytest.skip("real PRODUCTION_AGENTS_ANTHROPIC_API_KEY / VOYAGE_API_KEY not found in .env")
    for k, v in real.items():
        monkeypatch.setenv(k, v)
    import agent_runtime.config

    agent_runtime.config.reset_config()

    # Deterministic audio: 3.0s and 5.0s tones.
    intro_audio = tmp_path / "intro.wav"
    outro_audio = tmp_path / "outro.wav"
    for path, dur in ((intro_audio, 3.0), (outro_audio, 5.0)):
        subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
             f"sine=frequency=440:duration={dur}", str(path)],
            check=True,
        )

    script = tmp_path / "fixture-script.md"
    script.write_text(FIXTURE_SCRIPT)

    from agent_runtime import get_memory_store
    from edit_brief.agent import draft_sync

    seeded_ids = asyncio.run(_seed_takes(intro_audio, outro_audio))
    try:
        result = draft_sync(
            script, project_id=PROJECT, bpm=120, gap=0.5,
            output_path=tmp_path,  # keep the artifact out of the repo
        )

        rows = {r.section_id: r for r in result.brief.timeline}
        # Intro: measured 3.0s VO, source vo.
        assert rows["intro"].timing_source == "vo"
        assert rows["intro"].start_sec == 0.0
        assert rows["intro"].end_sec == pytest.approx(3.0, abs=0.05)
        # Outro: starts after intro + 0.5s gap, measured 5.0s VO.
        assert rows["outro"].timing_source == "vo"
        assert rows["outro"].start_sec == pytest.approx(3.5, abs=0.05)
        assert rows["outro"].end_sec == pytest.approx(8.5, abs=0.05)

        # Beat grid present and correct at 120 BPM.
        bg = result.brief.beat_grid
        assert bg is not None and bg.bpm == 120
        assert bg.beat_sec == 0.5 and bg.bar_sec == 2.0
        outro_prop = next(p for p in bg.boundary_proposals if p.section_id == "outro")
        assert outro_prop.nearest_beat_sec == 3.5  # 3.5 already on a beat at 120bpm

        assert result.status == "completed"
        print(f"\nSMOKE OK — brief at {result.brief_path}, cost ${result.cost_usd:.4f}")
    finally:
        asyncio.run(_delete_takes(get_memory_store(), seeded_ids))


async def _seed_takes(intro_audio: Path, outro_audio: Path) -> list[str]:
    from qdrant_client.models import PointStruct

    from agent_runtime import get_memory_store

    store = get_memory_store()
    await store.ensure_collection(COLLECTION, 1024)
    embedder = store.embedding_client

    takes = [
        ("intro", str(intro_audio), "Intro take text for the smoke fixture."),
        ("outro", str(outro_audio), "Outro take text for the smoke fixture."),
    ]
    vectors = await embedder.embed([t[2] for t in takes], input_type="document")
    now = datetime.now(UTC).isoformat()
    ids: list[str] = []
    points = []
    for (section_id, audio_path, text), vec in zip(takes, vectors):
        pid = str(uuid.uuid4())
        ids.append(pid)
        points.append(PointStruct(id=pid, vector=vec, payload={
            "memory_type": "take",
            "entry_id": pid,
            "project_id": PROJECT,
            "section_id": section_id,
            "audio_path": audio_path,
            "text": text,
            "reaction": "loved",
            "status": "complete",
            "created_at": now,
        }))
    await store._client.upsert(collection_name=COLLECTION, points=points)
    return ids


async def _delete_takes(store, ids: list[str]) -> None:
    await store._client.delete(collection_name=COLLECTION, points_selector=ids)
