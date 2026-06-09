"""explain — grounded tutor deep-dive (mocked Claude + mocked retrieve_context).

Invariants under test: own technique lessons are surfaced at EVERY level; the
--level dial changes only the generic gloss (max_tokens) volume; the Claude cost
lands in the budget; the GPU tracker is never touched.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_runtime.config import get_config
from visual_generation.constants import (
    AGENT_SUBDIR,
    EXPLAIN_LEVELS,
    EXPLAIN_MAX_TOKENS,
    GPU_LEDGER_FILENAME,
)
from visual_generation.explain import explain, resolve_level
from visual_generation.models import TechniqueLesson
from visual_generation.retrieval import RetrievedContext


def _fake_client(text: str = "Flux runs CFG≈1.0; guidance is the control knob.") -> MagicMock:
    msg = MagicMock()
    msg.usage.input_tokens = 200
    msg.usage.output_tokens = 80
    msg.content = [MagicMock(text=text)]
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=msg)
    return client


def _mock_store() -> MagicMock:
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    return store


def _ctx_with_lessons() -> RetrievedContext:
    return RetrievedContext(
        technique_lessons=[
            (0.9, TechniqueLesson(statement="CFG>7 washed skin on flux1-dev.",
                                  valence="negative", scope="settings", confirmed=True)),
        ],
        tutorial_hits=[(0.6, "Flux guidance replaces the negative prompt.")],
    )


def _patch_retrieve(monkeypatch, ctx: RetrievedContext) -> None:
    explain_mod = importlib.import_module("visual_generation.explain")
    monkeypatch.setattr(explain_mod, "retrieve_context", AsyncMock(return_value=ctx))


def _gpu_ledger_path() -> Path:
    return get_config().agent_data_dir / AGENT_SUBDIR / GPU_LEDGER_FILENAME


@pytest.mark.parametrize("level", EXPLAIN_LEVELS)
@pytest.mark.asyncio
async def test_own_lessons_present_at_every_level(monkeypatch, level: str) -> None:
    _patch_retrieve(monkeypatch, _ctx_with_lessons())
    client = _fake_client()

    result = await explain("cfg on flux", level=level, store=_mock_store(), llm_client=client)

    # INVARIANT: own lessons surfaced regardless of level.
    assert result.own_lessons == ["CFG>7 washed skin on flux1-dev."]
    assert result.level == level
    # The dial drives max_tokens (the gloss-volume lever), not the lessons.
    _, kwargs = client.messages.create.call_args
    assert kwargs["max_tokens"] == EXPLAIN_MAX_TOKENS[level]


@pytest.mark.asyncio
async def test_level_changes_only_gloss_volume(monkeypatch) -> None:
    _patch_retrieve(monkeypatch, _ctx_with_lessons())
    full_client, quiet_client = _fake_client(), _fake_client()

    full = await explain("x", level="full", store=_mock_store(), llm_client=full_client)
    quiet = await explain("x", level="quiet", store=_mock_store(), llm_client=quiet_client)

    # Same lessons, different gloss budget.
    assert full.own_lessons == quiet.own_lessons
    full_tokens = full_client.messages.create.call_args.kwargs["max_tokens"]
    quiet_tokens = quiet_client.messages.create.call_args.kwargs["max_tokens"]
    assert full_tokens > quiet_tokens


@pytest.mark.asyncio
async def test_claude_cost_in_budget_gpu_untouched(monkeypatch) -> None:
    _patch_retrieve(monkeypatch, _ctx_with_lessons())

    result = await explain("x", level="concise", store=_mock_store(), llm_client=_fake_client())

    # Claude cost recorded (sonnet pricing × tokens > 0).
    assert result.cost_usd > 0.0
    # GPU axis untouched — the agent-local ledger was never written.
    assert not _gpu_ledger_path().exists()


@pytest.mark.asyncio
async def test_quiet_degenerates_with_empty_context(monkeypatch) -> None:
    _patch_retrieve(monkeypatch, RetrievedContext())  # cold start, no lessons
    client = _fake_client(text="A one-line gloss.")

    result = await explain("obscure concept", level="quiet", store=_mock_store(), llm_client=client)

    assert result.own_lessons == []          # nothing to surface
    assert result.had_context is False
    assert result.gloss                       # still produces a minimal gloss
    client.messages.create.assert_awaited_once()


def test_resolve_level_precedence(monkeypatch) -> None:
    # Explicit flag wins.
    assert resolve_level("full") == "full"
    # Invalid → default.
    assert resolve_level("nonsense") == "concise"
    # Env override when no flag.
    monkeypatch.setenv("VISUALGEN_EXPLAIN_LEVEL", "full")
    assert resolve_level(None) == "full"
    monkeypatch.delenv("VISUALGEN_EXPLAIN_LEVEL", raising=False)
    assert resolve_level(None) == "concise"
