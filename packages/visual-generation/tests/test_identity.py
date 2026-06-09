from __future__ import annotations

from visual_generation.identity import derive_identity_bearing
from visual_generation.models import LoraRef, ModelAsset, VisualSpec


def _registry(*assets: ModelAsset):
    by_name = {a.name: a for a in assets}
    return lambda name: by_name.get(name)


def test_registry_flagged_model_makes_spec_identity_bearing() -> None:
    spec = VisualSpec(prompt="x", model="face.safetensors", identity_bearing=False)
    get = _registry(ModelAsset(name="face.safetensors", kind="checkpoint", identity_bearing=True))
    assert derive_identity_bearing(spec, get) is True


def test_registry_flagged_lora_makes_spec_identity_bearing() -> None:
    spec = VisualSpec(
        prompt="x",
        model="flux1-dev.safetensors",
        lora_stack=[LoraRef(name="char-lora.safetensors", strength=0.8)],
        identity_bearing=False,  # the file says no…
    )
    get = _registry(
        ModelAsset(name="flux1-dev.safetensors", kind="checkpoint"),
        ModelAsset(name="char-lora.safetensors", kind="lora", identity_bearing=True),  # …but the registry says yes
    )
    assert derive_identity_bearing(spec, get) is True


def test_spec_flag_can_escalate_even_when_registry_silent() -> None:
    # The spec declares identity-bearing; nothing in the registry is flagged.
    spec = VisualSpec(prompt="x", model="m.safetensors", identity_bearing=True)
    get = _registry(ModelAsset(name="m.safetensors", kind="checkpoint", identity_bearing=False))
    assert derive_identity_bearing(spec, get) is True


def test_non_identity_when_neither_flags() -> None:
    spec = VisualSpec(prompt="x", model="m.safetensors", identity_bearing=False)
    get = _registry(ModelAsset(name="m.safetensors", kind="checkpoint", identity_bearing=False))
    assert derive_identity_bearing(spec, get) is False


def test_unknown_models_fall_back_to_spec_flag() -> None:
    spec = VisualSpec(prompt="x", model="unregistered.safetensors", identity_bearing=False)
    assert derive_identity_bearing(spec, _registry()) is False
