"""Discovery layer — read the creative artifacts by `project_id`.

edit-brief is a READER, not an owner: it imports no sibling package. Foreign
collections are read generically by name through the runtime MemoryStore —
filter-only `scroll` for record enumeration (no embedding space involved) and
`query_by_vector` for the one semantic read (the best-effort music-BPM match).
Raw payload dicts are parsed into edit-brief's own thin discovery models holding
only the fields it consumes.

Every absence is a visible "missing input", never a failure or silent guess —
each read degrades to empty when its collection does not exist yet.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from agent_runtime import MemoryStore
from qdrant_client.models import FieldCondition, Filter, MatchValue

from edit_brief.constants import (
    FOOTAGE_EXTENSIONS,
    MEMORY_TYPE_GENERATION,
    MEMORY_TYPE_TAKE,
    MUSIC_COLLECTION,
    POSITIVE_VO_REACTIONS,
    VISUAL_COLLECTION,
    VOICEOVER_COLLECTION,
)
from edit_brief.models import (
    DiscoveredAsset,
    DiscoveredInputs,
    DiscoveredMusic,
    DiscoveredVOTake,
)
from edit_brief.probe import ffprobe_duration

logger = logging.getLogger(__name__)


async def _scroll_all(
    store: MemoryStore, collection: str, filters: Filter
) -> list[dict[str, Any]]:
    """Enumerate every payload matching `filters`, or [] if the collection is
    absent. Filter-only scroll with offset pagination — the voiceover-store
    pattern; no vector, no fixed-limit truncation."""
    payloads: list[dict[str, Any]] = []
    offset = None
    try:
        while True:
            records, offset = await store._client.scroll(
                collection_name=collection,
                scroll_filter=filters,
                limit=100,
                offset=offset,
                with_payload=True,
            )
            payloads.extend(r.payload or {} for r in records)
            if offset is None:
                break
    except Exception as exc:  # collection may not exist yet — degrade
        logger.debug("scroll of %s skipped (%s)", collection, exc)
        return []
    return payloads


def _filter(**eq: str) -> Filter:
    return Filter(
        must=[FieldCondition(key=k, match=MatchValue(value=v)) for k, v in eq.items()]
    )


# ── VO takes ──────────────────────────────────────────────────────────────────


def _select_take(payloads: list[dict[str, Any]]) -> tuple[dict[str, Any], bool]:
    """Take-selection rule: the newest positively-reacted take wins, else the
    newest overall. Returns (chosen_payload, ambiguous). `created_at` is ISO-8601
    so lexicographic max == chronological max."""
    positives = [p for p in payloads if p.get("reaction") in POSITIVE_VO_REACTIONS]
    pool = positives or payloads
    chosen = max(pool, key=lambda p: p.get("created_at", ""))
    # Ambiguous when more than one positive take exists (the director may have
    # liked several) — surfaced in the brief, not silently resolved.
    ambiguous = len(positives) > 1
    return chosen, ambiguous


async def discover_vo_takes(
    store: MemoryStore, project_id: str, section_ids: list[str]
) -> list[DiscoveredVOTake]:
    """The selected VO take per section, with its ffprobe-read duration. Only
    sections present in the script are returned (script order preserved)."""
    payloads = await _scroll_all(
        store,
        VOICEOVER_COLLECTION,
        _filter(memory_type=MEMORY_TYPE_TAKE, project_id=project_id),
    )
    by_section: dict[str, list[dict[str, Any]]] = {}
    for p in payloads:
        by_section.setdefault(p.get("section_id", ""), []).append(p)

    takes: list[DiscoveredVOTake] = []
    for section_id in section_ids:
        group = by_section.get(section_id)
        if not group:
            continue
        chosen, ambiguous = _select_take(group)
        audio_path = chosen.get("audio_path")
        takes.append(
            DiscoveredVOTake(
                section_id=section_id,
                audio_path=audio_path,
                duration_sec=ffprobe_duration(audio_path) if audio_path else None,
                reaction=chosen.get("reaction", "pending"),
                created_at=chosen.get("created_at", ""),
                ambiguous=ambiguous,
            )
        )
    return takes


# ── Music ─────────────────────────────────────────────────────────────────────


async def discover_music(
    store: MemoryStore,
    *,
    music_file: str | None,
    bpm: int | None,
    music_hint: str | None,
) -> DiscoveredMusic:
    """Resolve the track file/duration (from --music) and BPM. BPM precedence:
    --bpm flag > best-effort semantic match against music_curation_memory (a
    surfaced PROPOSAL) > none (beat grid omitted with a notation)."""
    duration = ffprobe_duration(music_file) if music_file else None

    if bpm is not None:
        return DiscoveredMusic(
            file=music_file, duration_sec=duration, bpm=bpm, bpm_source="flag"
        )

    matched_bpm, matched_title = await _match_bpm(store, music_hint)
    if matched_bpm is not None:
        return DiscoveredMusic(
            file=music_file,
            duration_sec=duration,
            bpm=matched_bpm,
            bpm_source="matched",
            matched_title=matched_title,
        )

    return DiscoveredMusic(file=music_file, duration_sec=duration, bpm_source="none")


async def _match_bpm(
    store: MemoryStore, music_hint: str | None
) -> tuple[int | None, str | None]:
    """Best-effort: semantically match the script's Music: hint against logged
    generations and read the top hit's BPM. Returns (None, None) when there is no
    hint, no collection, or the top hit has no BPM. Always a labeled proposal —
    never silently adopted (the director sees matched_title and can override)."""
    if not music_hint:
        return None, None
    try:
        [vec] = await store.embedding_client.embed([music_hint], input_type="query")
        hits = await store.query_by_vector(
            MUSIC_COLLECTION,
            vec,
            limit=1,
            filters=_filter(memory_type=MEMORY_TYPE_GENERATION),
        )
    except Exception as exc:
        logger.debug("music BPM match skipped (%s)", exc)
        return None, None
    if not hits:
        return None, None
    _id, _score, payload = hits[0]
    bpm = payload.get("bpm")
    if not isinstance(bpm, int):
        return None, None
    return bpm, payload.get("suggested_track_title")


# ── Generated assets + director footage ───────────────────────────────────────


async def discover_assets(
    store: MemoryStore, project_id: str, footage_dir: str | None
) -> list[DiscoveredAsset]:
    """Generated assets (rich metadata → precise mapping) from
    visual_generation_memory by `project`, plus a thin scan of --footage."""
    assets: list[DiscoveredAsset] = []

    gen_payloads = await _scroll_all(
        store,
        VISUAL_COLLECTION,
        _filter(memory_type=MEMORY_TYPE_GENERATION, project=project_id),
    )
    for p in gen_payloads:
        path = p.get("asset_path")
        if not path:
            continue
        assets.append(
            DiscoveredAsset(
                kind="generated",
                path=path,
                description=p.get("caption"),
                prompt=p.get("prompt"),
                created_at=p.get("created_at", ""),
            )
        )

    assets.extend(_scan_footage(footage_dir))
    return assets


def _scan_footage(footage_dir: str | None) -> list[DiscoveredAsset]:
    """The one input with no record: scan + ffprobe filename + duration.
    Descriptions are optional director-authored `<file>.txt` sidecars."""
    if not footage_dir:
        return []
    root = Path(footage_dir)
    if not root.is_dir():
        logger.warning("--footage path is not a directory: %s", root)
        return []
    out: list[DiscoveredAsset] = []
    for path in sorted(root.iterdir()):
        if not path.is_file() or path.suffix.lower() not in FOOTAGE_EXTENSIONS:
            continue
        sidecar = path.with_suffix(path.suffix + ".txt")
        description = (
            sidecar.read_text(encoding="utf-8").strip() if sidecar.is_file() else None
        )
        out.append(
            DiscoveredAsset(
                kind="footage",
                path=str(path),
                description=description,
                duration_sec=ffprobe_duration(path),
            )
        )
    return out


# ── Top-level ─────────────────────────────────────────────────────────────────


async def discover_inputs(
    store: MemoryStore,
    *,
    project_id: str,
    section_ids: list[str],
    music_hint: str | None,
    footage_dir: str | None,
    music_file: str | None,
    bpm: int | None,
) -> DiscoveredInputs:
    """Assemble the full discovery picture. Free — no LLM, no external spend."""
    vo_takes = await discover_vo_takes(store, project_id, section_ids)
    music = await discover_music(
        store, music_file=music_file, bpm=bpm, music_hint=music_hint
    )
    assets = await discover_assets(store, project_id, footage_dir)
    return DiscoveredInputs(
        project_id=project_id, vo_takes=vo_takes, music=music, assets=assets
    )
