"""Shared construction helpers for the visual-generation CLI.

The generation turn (`draft`/`generate`/`report`) is Step 4; this module
currently provides only the store wiring the `model`/`workflow` CLI surfaces use.
"""

from __future__ import annotations

from agent_runtime import MemoryStore, get_memory_store

from visual_generation.store import VisualGenerationStore


def _get_stores() -> tuple[VisualGenerationStore, MemoryStore]:
    ms = get_memory_store()
    store = VisualGenerationStore(ms)
    return store, ms
