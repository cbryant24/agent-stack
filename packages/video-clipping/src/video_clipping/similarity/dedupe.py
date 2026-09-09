"""Intra-run duplicate detection on Voyage embeddings.

Iterates in acceptance order; keeps a decision if its cosine similarity vs
every previously-kept decision is < threshold. Duplicates are flipped to
`action="exclude"`, `exclude_reason="duplicate_of_previous"` and returned in
the excluded bucket.

Voyage vectors come pre-L2-normalized, so cosine == dot product. Pure Python
is fine at Phase-1 N (≲ a few hundred).
"""

from __future__ import annotations

from video_clipping.constants import SIMILARITY_THRESHOLD
from video_clipping.models import ClipDecision


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def dedupe(
    decisions: list[ClipDecision],
    embeddings: list[list[float]],
    threshold: float = SIMILARITY_THRESHOLD,
) -> tuple[list[ClipDecision], list[ClipDecision]]:
    """Split `decisions` into (kept, duped).

    `decisions[i]` corresponds to `embeddings[i]`. The order determines which
    of a pair survives — the earlier decision wins.
    """
    if len(decisions) != len(embeddings):
        raise ValueError(
            f"decisions ({len(decisions)}) and embeddings ({len(embeddings)}) length mismatch"
        )

    kept: list[ClipDecision] = []
    duped: list[ClipDecision] = []
    kept_vectors: list[list[float]] = []

    for decision, vector in zip(decisions, embeddings, strict=True):
        is_duplicate = any(_dot(vector, kv) >= threshold for kv in kept_vectors)
        if is_duplicate:
            duped.append(
                decision.model_copy(
                    update={
                        "action": "exclude",
                        "exclude_reason": "duplicate_of_previous",
                    }
                )
            )
        else:
            kept.append(decision)
            kept_vectors.append(vector)
    return kept, duped
