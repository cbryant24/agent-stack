"""Local JSON-backed model/LoRA registry.

Models, checkpoints, and LoRAs are concrete named assets looked up by `name`,
never embedded or semantically searched — so they live in a plain JSON file, not
in Qdrant. This is the voice-registry analog. `VisualGenerationStore` owns an
instance so the store stays the single persistence surface.

`add()` is the programmatic register path (upsert by name, sets
`identity_bearing`). `replace()` is the wholesale-rewrite seam the Step-3
`model sync` writes through after parsing ComfyUI's /object_info.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from agent_runtime import get_config

from visual_generation.models import ModelAsset


def _default_path() -> Path:
    return get_config().agent_data_dir / "visual-generation" / "models.json"


class ModelRegistry:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _default_path()

    @property
    def path(self) -> Path:
        return self._path

    def _write(self, assets: list[ModelAsset]) -> None:
        """Atomically rewrite the registry: temp file then rename, so a crash
        mid-write can't leave a truncated registry."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = [a.to_dict() for a in assets]
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)

    def add(self, asset: ModelAsset) -> None:
        """Register a single asset, upserting by `name` (a re-add with the same
        name replaces the prior entry). This is the path that sets
        `identity_bearing`."""
        assets = [a for a in self.list_models() if a.name != asset.name]
        assets.append(asset)
        self._write(assets)

    def remove(self, name: str) -> bool:
        """Unregister the asset named `name`. Returns True if one was removed.

        Registry-only: does not touch the file on any pod (the drafter selects
        LoRAs from the registry, so removing the entry is what stops it being
        stacked). A later `model sync` re-adds a same-named file present on the
        pod as a fresh entry with default (non-identity) metadata."""
        assets = self.list_models()
        kept = [a for a in assets if a.name != name]
        if len(kept) == len(assets):
            return False
        self._write(kept)
        return True

    def replace(self, assets: list[ModelAsset]) -> None:
        """Overwrite the whole registry with `assets` (wholesale).

        # step 3: `model sync` populates the registry from ComfyUI /object_info
        # via this seam.
        """
        self._write(assets)

    def list_models(self) -> list[ModelAsset]:
        """Return all registered assets, or [] if the registry has never been written."""
        if not self._path.exists():
            return []
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        return [ModelAsset.from_dict(item) for item in raw]

    def get_model(self, name: str) -> ModelAsset | None:
        """Look up a single asset by name, or None if absent."""
        for asset in self.list_models():
            if asset.name == name:
                return asset
        return None
