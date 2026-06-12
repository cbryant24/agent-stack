"""Lesson distillation — propose durable editing-preference lessons.

Distillation is a tap on the diagnosis, not a second engine. A craft/taste rule
that would hold for the next project (not a project-scoped fix referencing "the
bridge") is proposed to `user_knowledge` via the runtime's propose→confirm flow,
domain `editing_preference`, with provenance (source project, feedback verbatim,
date).

v1 is PROPOSE-ONLY: a revise run writes drafts and surfaces their ids; the
director gates `confirm` out of band. Auto-confirming would write durable,
retrieval-affecting knowledge from a single unreviewed feedback turn — exactly
the over-generalization the propose→confirm gate exists to stop.
"""
from __future__ import annotations

import logging

from agent_runtime import UserKnowledgeStore

from feedback_iteration.constants import EDITING_PREFERENCE_DOMAIN
from feedback_iteration.models import LessonCandidate

logger = logging.getLogger(__name__)


async def propose_lessons(
    uks: UserKnowledgeStore,
    candidates: list[LessonCandidate],
    *,
    source_ref: str,
    feedback_verbatim: list[str],
    confidence_default: str = "medium",
) -> list[str]:
    """Propose each candidate as an `editing_preference` draft. Returns draft ids.
    Never confirms — confirmation is the director's gated step."""
    draft_ids: list[str] = []
    for cand in candidates:
        try:
            draft = await uks.propose_entry(
                cand.statement,
                domain=EDITING_PREFERENCE_DOMAIN,
                source_type="feedback",
                source_ref=source_ref,
                examples=feedback_verbatim,
                confidence=cand.confidence or confidence_default,
            )
        except Exception as exc:  # a lesson proposal must never fail the revision
            logger.warning("lesson proposal skipped: %s", exc)
            continue
        draft_ids.append(draft.draft_id)
    return draft_ids
