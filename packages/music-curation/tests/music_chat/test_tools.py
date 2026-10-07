"""Read, craft, reaction and write tools: argument mapping to the library, and the reaction rules."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock

import pytest

import music_curation.chat.tools.craft as craft_mod
import music_curation.chat.tools.reads as reads_mod
from music_curation.chat.schemas import ReactionInput, check_reaction
from music_curation.chat.tools import tool_pack
from music_curation.models import MusicResult, SunoPrompt, TasteLesson
from music_curation.retrieval import RetrievedContext

from .conftest import Built, make_gens  # type: ignore[import-not-found]

pytestmark = pytest.mark.asyncio


def tools(b: Built) -> dict[str, Any]:
    return {t.name: t for t in tool_pack(b.state)}


async def call(t: dict[str, Any], name: str, **kw: Any) -> Any:
    return await t[name].handler(t[name].input_model(**kw))


# ── reads ────────────────────────────────────────────────────────────────────


async def test_reads_write_nothing_and_remember_the_ids_they_show(
    build: Callable[..., Built], monkeypatch: pytest.MonkeyPatch
) -> None:
    gens = make_gens(3)
    gens[1].chain_root_id = gens[0].entry_id
    gens[1].parent_id = gens[0].entry_id
    gens[0].chain_root_id = gens[0].entry_id
    b = build(gens=gens)
    ctx = RetrievedContext(prior_generations=[(0.9, gens[0])],
                           taste_lessons=[(0.8, TasteLesson(statement="warm tape", valence="positive", scope="production"))])
    spy = AsyncMock(return_value=ctx)
    monkeypatch.setattr(reads_mod, "retrieve_context", spy)
    t = tools(b)

    r = await call(t, "recall", query="lo-fi", limit=3)
    assert "Prior Generations (1)" in r.text and "Track 1" in r.text and gens[0].entry_id in r.text
    assert spy.await_args.kwargs == {"generation_limit": 3, "taste_limit": 3, "suno_fact_limit": 3}
    r = await call(t, "review_pending")
    assert "3 pending generation(s)" in r.text and r.data["generation_ids"] == [g.entry_id for g in gens]
    r = await call(t, "chain_show", generation="00000002")          # a prefix of an id already shown
    assert "Chain (2 entries)" in r.text and r.data["chain_root_id"] == gens[0].entry_id
    r = await call(t, "chain_show", generation="nope")
    assert r.is_error and "not a generation id" in r.text
    assert b.writes == []


# ── generate ─────────────────────────────────────────────────────────────────


async def test_generate_calls_curate_with_the_per_call_cap_and_relays_the_question(
    build: Callable[..., Built], monkeypatch: pytest.MonkeyPatch
) -> None:
    result = MusicResult(
        prompts=[SunoPrompt(style_field="lo-fi, 80 BPM, jazz piano")], suggested_titles=["Night Drive"],
        theory_reasoning="warm", run_id="r1", status="completed", cost_usd=0.04, items_processed=1, wall_time_sec=2.0,
        generation_ids=["gen-0001-xyz"],
        pending_question={"ask": True, "question": "Vocals or instrumental?", "suggestion": "instrumental", "reasoning": "unclear"},
    )
    spy = AsyncMock(return_value=result)
    monkeypatch.setattr(craft_mod, "_curate", spy)
    b = build()
    t = tools(b)
    spec = t["generate"]
    a = spec.input_model(request="lo-fi for a night drive")
    assert spec.estimate_cost(a) == 0.10 and "saved as a pending generation automatically" in spec.preview(a)
    r = await spec.handler(a)
    assert spy.await_args.kwargs["budget"].max_cost_usd == 0.60 and spy.await_args.kwargs["skip_question"] is False
    assert "lo-fi, 80 BPM, jazz piano" in r.text and "gen-0001-xyz" in r.text and "Q: Vocals or instrumental?" in r.text
    assert "Put it to the director" in r.text
    assert r.data["cost_usd"] == 0.04 and r.data["generation_ids"] == ["gen-0001-xyz"]
    assert b.state.seen == {"gen-0001-xyz": "Night Drive"}


# ── the reaction rules (golden) ──────────────────────────────────────────────

GOLDEN = [
    # reaction, rendered_as_prompted, rating -> refusal fragment, open question?, note fragment
    ("disliked", True, None, None, False, None),
    ("disliked", False, None, "this is 'prompt_failed'", False, None),
    ("disliked", None, None, None, True, None),
    ("prompt_failed", False, None, None, False, None),
    ("prompt_failed", True, None, "this is 'disliked'", False, None),
    ("prompt_failed", None, None, None, True, None),
    ("loved", None, 5, None, False, None),
    ("liked_with_changes", None, 3, None, False, None),
    ("disliked", True, 2, None, False, "unusual for 'disliked'"),
    ("never_ran", None, 3, "does not apply to 'never_ran'", False, None),
    ("copyright_blocked", None, None, None, False, None),
    ("lost_track", None, 1, "does not apply to 'lost_track'", False, None),
]


@pytest.mark.parametrize("reaction,rendered,rating,refusal,question,note", GOLDEN)
async def test_reaction_rules(reaction: str, rendered: bool | None, rating: int | None, refusal: str | None,
                              question: bool, note: str | None) -> None:
    c = check_reaction(ReactionInput(generation="latest", reaction=reaction, rating=rating,  # type: ignore[arg-type]
                                     raw_feedback="the hats are too bright", rendered_as_prompted=rendered))
    assert (refusal is None and c.refusals == []) or (refusal and refusal in "; ".join(c.refusals))
    assert bool(c.open_questions) is question
    assert (note is None and c.notes == []) or (note and note in "; ".join(c.notes))


async def test_empty_feedback_is_refused() -> None:
    c = check_reaction(ReactionInput(generation="latest", reaction="loved", raw_feedback="  "))
    assert "raw_feedback is empty" in c.refusals[0]


async def test_propose_reaction_stores_nothing_and_queues_the_writes_for_exit(build: Callable[..., Built]) -> None:
    gens = make_gens(2)
    b = build(gens=gens)
    t = tools(b)
    r = await call(t, "propose_reaction", generation="latest", reaction="disliked", rendered_as_prompted=True,
                   raw_feedback="too busy in the low end", notes="thin the bass", context="competes with the vocal",
                   taste_lessons=[{"statement": "sparse low end under vocals", "valence": "positive", "scope": "arrangement"}])
    assert not r.is_error and r.text.startswith("PROPOSED (nothing is stored): reaction to Track 2 (00000002)  [DISLIKED]")
    assert "Feedback (verbatim): too busy in the low end" in r.text and "Taste lesson candidate" in r.text
    assert b.writes == [] and r.data["gen_id"] == gens[1].entry_id
    proposals = b.state.unwritten_proposals()
    assert [p.tool for p in proposals] == ["report", "taste_add"]
    assert proposals[0].payload["generation"] == gens[1].entry_id and "raw_feedback" not in proposals[0].payload

    r = await call(t, "propose_reaction", generation="latest", reaction="disliked", raw_feedback="meh")
    assert not r.is_error and "OPEN QUESTION: Did Suno render what the prompt asked for?" in r.text
    assert "Ask the director" in r.text and len(b.state.unwritten_proposals()) == 2     # nothing new queued

    r = await call(t, "propose_reaction", generation="latest", reaction="disliked", rendered_as_prompted=False,
                   raw_feedback="it ignored the tempo")
    assert r.is_error and "this is 'prompt_failed'" in r.text
    r = await call(t, "propose_reaction", generation="zzzzzzzzzz", reaction="loved", raw_feedback="great")
    assert r.is_error and r.data["open_questions"]


# ── writes ───────────────────────────────────────────────────────────────────


async def test_report_maps_its_arguments_onto_the_library_write(build: Callable[..., Built]) -> None:
    gens = make_gens(2)
    b = build(gens=gens)
    t = tools(b)
    spec = t["report"]
    a = spec.input_model(generation=gens[0].entry_id, reaction="liked_with_changes", rating=4, notes="slower",
                         context="groove is right")
    assert await spec.precheck(a) is None
    preview = await spec.preview(a)
    assert preview.startswith("Record reaction on Track 1 (00000001): liked_with_changes ★4") and "notes: slower" in preview
    r = await spec.handler(a)
    ((args, kwargs),) = b.wrote("update_generation_reaction")
    assert args == (gens[0].entry_id, "liked_with_changes")
    assert kwargs == {"notes": "slower", "context": "groove is right", "rating": 4}
    assert r.text == "Recorded: Track 1 → liked_with_changes ★4"

    assert "Could not resolve" in await spec.precheck(spec.input_model(generation="nope", reaction="loved"))
    refusal = await spec.precheck(spec.input_model(generation="latest", reaction="never_ran", rating=2))
    assert refusal == "a rating does not apply to 'never_ran': the track was not heard"
    warn = await spec.preview(spec.input_model(generation="latest", reaction="disliked", rating=2))
    assert "ratings are meaningful for positive reactions" in warn


async def test_taste_add_and_fact_add_call_the_library_functions(build: Callable[..., Built]) -> None:
    b = build()
    t = tools(b)
    r = await call(t, "taste_add", statement="no trap hats", valence="negative", scope="instrumentation")
    ((args, _),) = b.wrote("upsert_taste")
    lesson = args[0]
    assert (lesson.statement, lesson.valence, lesson.scope, lesson.confirmed) == ("no trap hats", "negative", "instrumentation", True)
    assert "Added taste lesson [negative/instrumentation]" in r.text
    assert "Add a confirmed taste lesson [negative/instrumentation]" in t["taste_add"].preview(
        t["taste_add"].input_model(statement="no trap hats", valence="negative", scope="instrumentation"))

    r = await call(t, "fact_add", statement="style field caps at 1000 chars")
    ((entries, source_ref),) = b.wrote("bulk_load_verified")
    assert entries == [{"statement": "style field caps at 1000 chars", "domain": "suno_mechanics", "confidence": "high"}]
    assert source_ref == "manual:chat" and "entry-0" in r.text
