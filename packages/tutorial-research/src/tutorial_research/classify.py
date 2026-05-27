from __future__ import annotations

import re
from typing import Literal

_RETRIEVE_PATTERNS = (
    "find",
    "search existing",
    "what do we have",
    "what have we",
    "show me what",
    "list what",
)


def classify_request(
    request: str,
    explicit: Literal["research", "ingest", "retrieve"] | None = None,
) -> Literal["research", "ingest", "retrieve"]:
    if explicit is not None:
        return explicit
    if re.search(r"https?://", request):
        return "ingest"
    lower = request.lower()
    if any(p in lower for p in _RETRIEVE_PATTERNS):
        return "retrieve"
    return "research"
