"""Seed ingest with the answers coming from a decision source. The terminal and the chat must
produce the same writes for the same answers: only the source of the decision differs
(docs/decisions-mode-spec.md)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import music_curation.seed_ingestion as si
from music_curation.chat.tools import tool_pack
from music_curation.seed_ingestion import ingest_seed, list_taste_queue

from .conftest import Built, seed_session  # type: ignore[import-not-found]

pytestmark = pytest.mark.asyncio

# The director's answers: facts yes; lesson 1 confirm, 2 edit, 3 defer; template 1 yes, 2 no.
CHAT_ARGS = dict(
    ingest_facts=True,
    taste=[{"n": 1, "decision": "confirm"}, {"n": 2, "decision": "edit", "text": "no bright cymbals on ballads"},
           {"n": 3, "decision": "defer"}],
    templates=[{"n": 1, "accept": True}, {"n": 2, "accept": False}],
)
TERMINAL_PROMPTS = ["y", "e", "no bright cymbals on ballads", "d"]     # click.prompt answers, in order
TERMINAL_CONFIRMS = [True, True, False]                                # facts, template 1, template 2


@pytest.fixture
def seed_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "cali-chill.md"
    path.write_text("# seed\n")
    monkeypatch.setattr(si, "parse_file", lambda p: seed_session())
    return path


def tools(b: Built) -> dict[str, Any]:
    return {t.name: t for t in tool_pack(b.state)}


def summary(b: Built) -> dict[str, Any]:
    """What reached the stores, reduced to values (ids and timestamps differ run to run)."""
    (taste,) = [a[0] for a, _ in b.wrote("upsert_taste_bulk")]
    (templates,) = [a[0] for a, _ in b.wrote("upsert_templates_bulk")]
    (gens,) = [a[0] for a, _ in b.wrote("upsert_generations_bulk")]
    ((facts, source_ref),) = b.wrote("bulk_load_verified")
    return {
        "taste": [(t.statement, t.valence, t.scope, t.confirmed) for t in taste],
        "templates": [t.name for t in templates],
        "generations": [(g.style_field, g.reaction) for g in gens],
        "facts": [f["statement"] for f in facts], "source_ref": source_ref,
        "queued": sorted(d.statement for _, d in list_taste_queue()),
        "order": b.names,
    }


async def test_the_terminal_and_the_chat_write_the_same_things_for_the_same_answers(
    build: Callable[..., Built], seed_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 1. the terminal answers, through the unchanged prompts
    prompts, confirms = list(TERMINAL_PROMPTS), list(TERMINAL_CONFIRMS)
    monkeypatch.setattr(si.click, "prompt", lambda *a, **k: prompts.pop(0))
    monkeypatch.setattr(si.click, "confirm", lambda *a, **k: confirms.pop(0))
    term = build()
    report = await ingest_seed(seed_file, echo=lambda line: None, curation_store=term.store, uks=term.uks)
    terminal = summary(term)
    assert prompts == [] and confirms == [] and report.deferred_taste == 1
    for path, _ in list_taste_queue():
        path.unlink()

    # 2. the chat answers, through the tool
    def no_terminal(*a: Any, **k: Any) -> Any:
        raise AssertionError("the chat path must not prompt at a terminal")

    monkeypatch.setattr(si.click, "prompt", no_terminal)
    monkeypatch.setattr(si.click, "confirm", no_terminal)
    chat = build()
    t = tools(chat)
    a = t["seed_ingest"].input_model(path=str(seed_file), **CHAT_ARGS)
    assert await t["seed_ingest"].precheck(a) is None
    r = await t["seed_ingest"].handler(a)

    assert summary(chat) == terminal
    assert terminal["taste"] == [("explicit: no trap hats", "positive", "production", True),
                                 ("warm tape saturation", "positive", "production", True),
                                 ("no bright cymbals on ballads", "positive", "production", True)]
    assert terminal["templates"] == ["explicit-base", "beach-night"] and terminal["queued"] == ["slow intros"]
    assert terminal["facts"] == ["fact 0", "fact 1", "fact 2"] and terminal["source_ref"] == "file:///seeds/cali-chill.md"
    assert r.text == ("Imported 1 file(s): 2 generation(s), 3 Suno fact(s), 3 taste lesson(s), 2 template(s) written; "
                      "1 taste lesson(s) deferred to the review queue.")


async def test_yes_mode_is_unchanged(build: Callable[..., Built], seed_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(si.click, "prompt", lambda *a, **k: pytest.fail("--yes must not prompt"))
    monkeypatch.setattr(si.click, "confirm", lambda *a, **k: pytest.fail("--yes must not prompt"))
    b = build()
    said: list[str] = []
    report = await ingest_seed(seed_file, auto_confirm=True, echo=said.append, curation_store=b.store, uks=b.uks)
    assert report.totals == {"generations": 2, "suno_facts": 3, "taste_lessons": 4, "templates": 3}
    assert report.deferred_taste == 0 and "  → 4 taste lessons written" in said and "  Templates:       3" in said


async def test_a_dry_run_writes_nothing(build: Callable[..., Built], seed_file: Path) -> None:
    b = build()
    report = await ingest_seed(seed_file, dry_run=True, echo=lambda line: None, curation_store=b.store, uks=b.uks)
    assert b.writes == [] and report.dry_run and report.totals["taste_lessons"] == 4


async def test_preview_numbers_every_inferred_item_and_writes_nothing(build: Callable[..., Built], seed_file: Path) -> None:
    b = build()
    t = tools(b)
    r = await t["seed_preview"].handler(t["seed_preview"].input_model(path=str(seed_file)))
    assert "Nothing is written by this preview." in r.text
    assert "2 generation(s), 1 explicit taste lesson(s), 1 explicit template(s)" in r.text
    assert "  1. [positive/production] warm tape saturation" in r.text and "  3. [positive/production] slow intros" in r.text
    assert "  1. beach-night  swap: mood" in r.text and "  2. rain-drive" in r.text
    assert r.data["inferred_taste"] == 3 and r.data["inferred_templates"] == 2 and b.writes == []
    assert (await t["seed_preview"].handler(t["seed_preview"].input_model(path="/no/such/file"))).is_error


async def test_ingest_is_refused_until_every_inferred_item_has_a_decision(build: Callable[..., Built], seed_file: Path) -> None:
    b = build()
    t = tools(b)
    spec = t["seed_ingest"]
    refusal = await spec.precheck(spec.input_model(path=str(seed_file), ingest_facts=True,
                                                   taste=[{"n": 1, "decision": "confirm"}]))
    assert refusal and "no decision for inferred taste lesson(s) 2, 3" in refusal
    assert "no decision for inferred template(s) 1, 2" in refusal and "Run seed_preview and ask." in refusal
    refusal = await spec.precheck(spec.input_model(path=str(seed_file), **{
        **CHAT_ARGS, "taste": [{"n": 1, "decision": "edit"}, {"n": 2, "decision": "skip"}, {"n": 3, "decision": "skip"},
                               {"n": 9, "decision": "skip"}]}))
    assert "no inferred taste lesson numbered 9 (the file has 3)" in refusal
    assert "taste lesson 1: 'edit' needs the director's text" in refusal
    bad = await spec.handler(spec.input_model(path=str(seed_file), ingest_facts=True))
    assert bad.is_error and b.writes == []


async def test_the_ingest_confirm_panel_states_each_decision(build: Callable[..., Built], seed_file: Path) -> None:
    t = tools(build())
    panel = await t["seed_ingest"].preview(t["seed_ingest"].input_model(path=str(seed_file), **CHAT_ARGS))
    assert "Suno facts: 3 WRITTEN to user_knowledge" in panel
    assert "  1. CONFIRM  [positive/production] warm tape saturation" in panel
    assert "  2. EDIT     [positive/production] avoid bright cymbals\n       written as: no bright cymbals on ballads" in panel
    assert "  3. DEFER    [positive/production] slow intros" in panel
    assert "  1. ADD  beach-night" in panel and "  2. SKIP rain-drive" in panel


# ── the deferred queue ───────────────────────────────────────────────────────


async def queued(build: Callable[..., Built], seed_file: Path) -> tuple[Built, dict[str, Any], list[str]]:
    b = build()
    t = tools(b)
    args = {**CHAT_ARGS, "taste": [{"n": i, "decision": "defer"} for i in (1, 2, 3)]}
    await t["seed_ingest"].handler(t["seed_ingest"].input_model(path=str(seed_file), **args))
    ids = [d.draft_id for _, d in list_taste_queue()]
    b.writes.clear()
    return b, t, ids


async def test_the_queue_lists_and_settles_one_lesson_at_a_time(build: Callable[..., Built], seed_file: Path) -> None:
    b, t, ids = await queued(build, seed_file)
    r = await t["taste_queue"].handler(t["taste_queue"].input_model())
    assert "3 deferred taste lesson(s) awaiting review" in r.text and set(r.data["draft_ids"]) == set(ids)
    by_text = {d.statement: d.draft_id for _, d in list_taste_queue()}
    spec = t["taste_queue_decide"]

    a = spec.input_model(draft=by_text["warm tape saturation"][:8], decision="confirm")
    assert await spec.precheck(a) is None and "Write this queued taste lesson" in await spec.preview(a)
    r = await spec.handler(a)
    ((args, _),) = b.wrote("upsert_taste_bulk")
    assert [x.statement for x in args[0]] == ["warm tape saturation"] and r.data["written"] == 1
    assert len(list_taste_queue()) == 2                              # the other two stay queued

    b.writes.clear()
    no_text = await spec.precheck(spec.input_model(draft=by_text["slow intros"], decision="edit"))
    assert no_text == "'edit' needs the director's text"
    a = spec.input_model(draft=by_text["slow intros"], decision="edit", text="intros under 8 bars")
    await spec.handler(a)
    assert [x.statement for x in b.wrote("upsert_taste_bulk")[0][0][0]] == ["intros under 8 bars"]

    b.writes.clear()
    a = spec.input_model(draft=by_text["avoid bright cymbals"], decision="delete")
    assert "WITHOUT writing it" in await spec.preview(a)
    r = await spec.handler(a)
    assert b.writes == [] and list_taste_queue() == [] and r.text.startswith("Deleted without writing")

    assert "no queued taste lesson matches" in await spec.precheck(spec.input_model(draft="zzzzzzzz", decision="confirm"))


async def test_the_terminal_queue_review_is_unchanged(
    build: Callable[..., Built], seed_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    b, _, _ = await queued(build, seed_file)
    order = [d.statement for _, d in list_taste_queue()]
    answers = ["y", "n", "x"]
    monkeypatch.setattr(si.click, "prompt", lambda *a, **k: answers.pop(0))
    said: list[str] = []
    n = await si.review_taste_queue(echo=said.append, curation_store=b.store)
    assert n == 1 and said[0] == "3 pending taste lesson(s):\n" and said[-1] == "\n1 taste lesson(s) confirmed and written."
    assert [x.statement for x in b.wrote("upsert_taste_bulk")[0][0][0]] == [order[0]]
    assert [d.statement for _, d in list_taste_queue()] == [order[1]]       # skipped stays; deleted is gone
