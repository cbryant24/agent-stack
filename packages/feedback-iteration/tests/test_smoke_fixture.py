"""Live revision smoke — the integration proof of the `revise` turn end to end.

Opt-in only: gated behind FEEDBACK_ITERATION_SMOKE=1 plus a reachable Qdrant and
real API keys in the repo `.env`. It NEVER runs (or charges) in the normal suite.

It copies the real `script-draft.edit-brief.md` into a tmp dir and revises it with
four feedback items: a middle-section timing change (exercises the downstream
cascade), a step rewrite, a durable-lesson candidate, and one deliberately
UNMAPPABLE item ("the drop feels too slow" — there is no drop/music in this
brief) to prove surface-don't-guess. It asserts the mechanical guarantees
(snapshot, version bump, version log) hard and prints the LLM-dependent mapping;
then it deletes any lesson drafts it wrote.

Run it with:
    FEEDBACK_ITERATION_SMOKE=1 uv run pytest \
        packages/feedback-iteration/tests/test_smoke_fixture.py -s
"""
from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

import pytest

from .conftest import requires_qdrant

SMOKE = pytest.mark.skipif(
    os.environ.get("FEEDBACK_ITERATION_SMOKE") != "1",
    reason="set FEEDBACK_ITERATION_SMOKE=1 to run the live revision smoke test",
)

REPO_ROOT = Path(__file__).resolve().parents[3]

FEEDBACK = (
    "tighten the calm underneath by 2 seconds\n"
    "the close fade should be 2 seconds, not 1\n"
    "I always want my calm sections to breathe less\n"
    "the drop feels too slow"
)


def _load_real_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (REPO_ROOT / ".env").read_text().splitlines():
        m = re.match(r"^([A-Z_]+)=(.*)$", line.strip())
        if m and m.group(2):
            env[m.group(1)] = m.group(2)
    return env


@SMOKE
@requires_qdrant
def test_revise_real_brief_end_to_end(tmp_path, monkeypatch):
    real = _load_real_env()
    if not real.get("ANTHROPIC_API_KEY") or not real.get("VOYAGE_API_KEY"):
        pytest.skip("real ANTHROPIC_API_KEY / VOYAGE_API_KEY not found in .env")
    for k, v in real.items():
        monkeypatch.setenv(k, v)
    import agent_runtime.config

    agent_runtime.config.reset_config()

    original = (REPO_ROOT / "script-draft.edit-brief.md").read_text(encoding="utf-8")
    brief = tmp_path / "script-draft.edit-brief.md"
    brief.write_text(original, encoding="utf-8")

    from agent_runtime import UserKnowledgeStore, get_memory_store
    from feedback_iteration.agent import revise_sync

    result = revise_sync(brief, FEEDBACK)
    out = brief.read_text(encoding="utf-8")

    try:
        # ── Mechanical guarantees (deterministic) ─────────────────────────────
        snap = tmp_path / "versions" / "script-draft.edit-brief.v1.md"
        assert snap.exists(), "no v1 snapshot taken"
        assert snap.read_text(encoding="utf-8") == original, "snapshot is not the verbatim pre-revision brief"
        assert "version: 2" in out and "version: 1" not in out, "frontmatter not bumped 1→2"
        assert "## Version log" in out and "### v2" in out, "no version-log entry"
        assert out != original, "brief was not patched in place"
        assert result.version_from == 1 and result.version_to == 2
        assert result.status == "completed"

        # ── Surface-don't-guess: the unmappable item is unapplied + logged ────
        assert any("the drop feels too slow" in u for u in result.unresolved), (
            f"unmappable item was not surfaced as unresolved: {result.unresolved}"
        )
        assert "Unresolved (unapplied)" in out

        # ── LLM-dependent mapping (printed, soft) ─────────────────────────────
        print("\n=== SMOKE: applied ===")
        for a in result.applied:
            print(f"  - {a}")
        print("=== SMOKE: unresolved ===")
        for u in result.unresolved:
            print(f"  - {u}")
        print(f"=== SMOKE: invalidated checks: {result.invalidated_checks}")
        print(f"=== SMOKE: lesson drafts: {result.lesson_draft_ids}")
        print(f"=== SMOKE: cost ${result.cost_usd:.4f}, {result.wall_time_sec:.1f}s")
        print(f"=== SMOKE: revised brief at {brief}")
    finally:
        # Clean up any lesson drafts written to the real agent-data dir.
        if result.lesson_draft_ids:
            uks = UserKnowledgeStore(get_memory_store())
            for draft_id in result.lesson_draft_ids:
                try:
                    asyncio.run(uks.reject_entry(draft_id))
                except Exception:
                    pass
