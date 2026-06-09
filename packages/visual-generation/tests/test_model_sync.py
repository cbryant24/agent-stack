from __future__ import annotations

from visual_generation.model_sync import parse_object_info, reconcile
from visual_generation.models import ModelAsset


def _object_info() -> dict:
    """A minimal /object_info with COMBO option lists on the loader nodes."""
    return {
        "CheckpointLoaderSimple": {
            "input": {"required": {"ckpt_name": [["sdxl_base.safetensors", "dreamshaper.safetensors"], {}]}}
        },
        "UNETLoader": {
            "input": {"required": {"unet_name": [["flux1-dev.safetensors"]]}}
        },
        "LoraLoader": {
            "input": {"required": {"lora_name": [["detail.safetensors", "char-lora.safetensors"]]}}
        },
        "VAELoader": {
            "input": {"required": {"vae_name": [["ae.safetensors"], {}]}}
        },
        "DualCLIPLoader": {
            "input": {"required": {
                "clip_name1": [["t5xxl_fp16.safetensors"]],
                "clip_name2": [["clip_l.safetensors"]],
            }}
        },
        # A non-loader node with no COMBO model field — must be ignored.
        "KSampler": {"input": {"required": {"steps": ["INT", {"default": 20}]}}},
    }


# ── parse_object_info ────────────────────────────────────────────────────────


def test_parse_object_info_maps_loaders_to_kinds() -> None:
    assets = parse_object_info(_object_info())
    by_name = {a.name: a for a in assets}

    assert by_name["sdxl_base.safetensors"].kind == "checkpoint"
    assert by_name["flux1-dev.safetensors"].kind == "checkpoint"  # UNETLoader → checkpoint
    assert by_name["char-lora.safetensors"].kind == "lora"
    assert by_name["ae.safetensors"].kind == "vae"
    assert by_name["t5xxl_fp16.safetensors"].kind == "clip"
    assert by_name["clip_l.safetensors"].kind == "clip"
    # All synced.
    assert all(a.source == "synced" for a in assets)
    # The KSampler INT field is not a model COMBO → nothing spurious.
    assert "steps" not in by_name


def test_parse_object_info_empty_when_no_loaders() -> None:
    assert parse_object_info({"KSampler": {"input": {"required": {"steps": ["INT"]}}}}) == []


# ── reconcile (the (b) rule) ─────────────────────────────────────────────────


def test_manual_identity_bearing_survives_present_merge() -> None:
    existing = [
        ModelAsset(name="char-lora.safetensors", kind="lora", identity_bearing=True,
                   base_model="flux1-dev", source="registered", metadata={"trigger": "ohwx"})
    ]
    synced = [ModelAsset(name="char-lora.safetensors", kind="lora", source="synced")]

    result = reconcile(existing, synced)

    merged = {a.name: a for a in result.merged}
    asset = merged["char-lora.safetensors"]
    assert asset.identity_bearing is True          # preserved
    assert asset.base_model == "flux1-dev"          # preserved
    assert asset.metadata == {"trigger": "ohwx"}    # preserved
    assert asset.source == "registered"             # manual provenance preserved
    assert asset.present_on_endpoint is True         # confirmed present
    assert result.refreshed == ["char-lora.safetensors"]


def test_new_synced_asset_is_added() -> None:
    result = reconcile([], [ModelAsset(name="new.safetensors", kind="checkpoint", source="synced")])
    assert [a.name for a in result.merged] == ["new.safetensors"]
    assert result.added == ["new.safetensors"]


def test_manual_asset_absent_from_pod_is_kept_and_flagged() -> None:
    existing = [
        ModelAsset(name="char-lora.safetensors", kind="lora", identity_bearing=True,
                   source="registered")
    ]
    # Pod reports something else entirely.
    synced = [ModelAsset(name="other.safetensors", kind="checkpoint", source="synced")]

    result = reconcile(existing, synced)

    merged = {a.name: a for a in result.merged}
    assert "char-lora.safetensors" in merged
    kept = merged["char-lora.safetensors"]
    assert kept.identity_bearing is True            # NOT lost
    assert kept.present_on_endpoint is False         # flagged absent
    assert result.kept_absent == ["char-lora.safetensors"]
    assert "other.safetensors" in merged             # new one added


def test_previously_synced_asset_absent_is_dropped() -> None:
    existing = [ModelAsset(name="stale.safetensors", kind="checkpoint", source="synced")]
    synced = [ModelAsset(name="fresh.safetensors", kind="checkpoint", source="synced")]

    result = reconcile(existing, synced)

    names = {a.name for a in result.merged}
    assert names == {"fresh.safetensors"}            # stale dropped, fresh added
    assert result.dropped == ["stale.safetensors"]
