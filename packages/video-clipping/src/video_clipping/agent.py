"""Shared construction helpers for the video-clipping CLI.

Mirrors visual_generation.agent — the store is built once per process from the
cached MemoryStore singleton.
"""

from __future__ import annotations

from agent_runtime import MemoryStore, get_memory_store

from video_clipping.store import VideoClippingStore


def _get_stores() -> tuple[VideoClippingStore, MemoryStore]:
    ms = get_memory_store()
    store = VideoClippingStore(ms)
    return store, ms
