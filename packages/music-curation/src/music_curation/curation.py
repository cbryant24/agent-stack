"""Writes the CLI and the chat share: record a reaction, add a taste lesson, add a Suno fact.

Each takes the store it writes through, so callers decide where the stores come from and nothing
here prompts or prints.
"""
from __future__ import annotations

from agent_runtime import UserKnowledgeStore

from music_curation.constants import POSITIVE_REACTIONS
from music_curation.models import Generation, TasteLesson
from music_curation.store import MusicCurationStore


def rating_warning(reaction: str, rating: int | None) -> str | None:
    """The advisory for a rating on a non-positive reaction (it is recorded anyway)."""
    if rating is not None and reaction not in POSITIVE_REACTIONS:
        return (
            f"Warning: --rating is unusual for '{reaction}' (ratings are meaningful "
            f"for positive reactions). Recording it anyway."
        )
    return None


async def record_reaction(
    gen_id: str,
    reaction: str,
    *,
    store: MusicCurationStore,
    rating: int | None = None,
    notes: str | None = None,
    context: str | None = None,
) -> Generation | None:
    """Record the director's reaction to a generation. Returns the generation as it was before
    the update, or None if there is no generation with that id (nothing is written)."""
    await store.ensure_collection()
    gen = await store.get_generation(gen_id)
    if gen is None:
        return None
    await store.update_generation_reaction(
        gen_id, reaction, notes=notes, context=context, rating=rating
    )
    return gen


async def add_taste(statement: str, valence: str, scope: str, *, store: MusicCurationStore) -> TasteLesson:
    """Add an explicit, confirmed taste lesson."""
    await store.ensure_collection()
    lesson = TasteLesson(statement=statement, valence=valence, scope=scope, confirmed=True)  # type: ignore[arg-type]
    await store.upsert_taste(lesson)
    return lesson


async def add_fact(
    statement: str,
    domain: str,
    confidence: str,
    *,
    uks: UserKnowledgeStore,
    source_ref: str = "manual:cli",
) -> str:
    """Add a verified fact to user_knowledge. Returns its entry id."""
    await uks.ensure_collection()
    entry_ids = await uks.bulk_load_verified(
        [{"statement": statement, "domain": domain, "confidence": confidence}],
        source_ref=source_ref,
    )
    return entry_ids[0]
