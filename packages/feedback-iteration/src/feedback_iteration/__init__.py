"""feedback-iteration — the revision agent.

Takes natural-language feedback on an edit-brief markdown artifact and produces a
state-preserving, anchor-addressed, in-place revision plus a version trail, and
distils durable editing-preference lessons as a byproduct of the diagnosis.

Revision is the spine; learning hangs off it. The agent imports only
`agent-runtime`; the edit-brief artifact is parsed as a FOREIGN artifact by its
anchors/structure (the format is the contract). All timing arithmetic is pure
code — the LLM never produces a number.
"""
from __future__ import annotations

from feedback_iteration.agent import revise, revise_sync
from feedback_iteration.models import RevisionResult

__all__ = ["revise", "revise_sync", "RevisionResult"]
