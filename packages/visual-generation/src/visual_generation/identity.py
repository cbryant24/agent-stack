"""Derive the security-critical `identity_bearing` decision from the registry.

The batch file is hand-editable, so a spec's declared `identity_bearing` is NOT
trusted for the security decision. The registry is the source of truth: an asset
flagged identity-bearing there makes any spec that uses it identity-bearing,
regardless of what the file says. The spec's declared flag can only **escalate**
to identity-bearing (a `True` is honored), never **downgrade** away from it.

`draft` may pre-fill the spec field from this same derivation (so the file is
honest); `generate` re-derives at spend time and never relies on the file.
"""

from __future__ import annotations

from collections.abc import Callable

from visual_generation.models import ModelAsset, VisualSpec


def derive_identity_bearing(
    spec: VisualSpec,
    get_model: Callable[[str], ModelAsset | None],
) -> bool:
    """True if the spec declares it OR any model/LoRA it uses is registry-flagged.

    `get_model` is the registry lookup (e.g. `store.get_model`). Stricter wins:
    the result is the OR over the spec's declared flag and the registry
    identity_bearing of its checkpoint/unet model and every LoRA in the stack.
    """
    names = [spec.model, *(lr.name for lr in spec.lora_stack)]
    for name in names:
        if not name:
            continue
        asset = get_model(name)
        if asset is not None and asset.identity_bearing:
            return True
    return bool(spec.identity_bearing)
