"""Local JSON-backed voice registry.

Voices are a bounded, enumerable set synced from ElevenLabs (the vendor is the
source of truth). They are listed and looked up by `voice_id`, never semantically
searched — so they live in a plain JSON file rewritten wholesale on each
`voice sync`, not in Qdrant. `VoiceoverDirectionStore` owns an instance of this
class so the store stays the single persistence surface.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from agent_runtime import get_config

from voiceover_direction.models import VoiceProfile


def _default_path() -> Path:
    return get_config().agent_data_dir / "voiceover" / "voices.json"


class VoiceRegistry:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _default_path()

    @property
    def path(self) -> Path:
        return self._path

    def replace(self, voices: list[VoiceProfile]) -> None:
        """Overwrite the whole registry with `voices` (the `voice sync` semantics).

        Writes to a temp file then atomically renames, so a crash mid-write can't
        leave a truncated registry.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = [v.to_dict() for v in voices]
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)

    def list_voices(self) -> list[VoiceProfile]:
        """Return all registered voices, or [] if the registry has never synced."""
        if not self._path.exists():
            return []
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        return [VoiceProfile.from_dict(item) for item in raw]

    def get_voice(self, voice_id: str) -> VoiceProfile | None:
        """Look up a single voice by id, or None if absent."""
        for voice in self.list_voices():
            if voice.voice_id == voice_id:
                return voice
        return None
