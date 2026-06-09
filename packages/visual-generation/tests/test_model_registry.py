from __future__ import annotations

from pathlib import Path

from visual_generation.model_registry import ModelRegistry
from visual_generation.models import ModelAsset


def _asset(name: str, kind: str = "checkpoint", identity_bearing: bool = False) -> ModelAsset:
    return ModelAsset(name=name, kind=kind, identity_bearing=identity_bearing)  # type: ignore[arg-type]


def test_empty_when_file_absent(tmp_path: Path) -> None:
    reg = ModelRegistry(path=tmp_path / "models.json")
    assert reg.list_models() == []
    assert reg.get_model("anything") is None


def test_add_then_list_get_round_trip(tmp_path: Path) -> None:
    reg = ModelRegistry(path=tmp_path / "models.json")
    reg.add(_asset("flux1-dev"))
    reg.add(
        ModelAsset(
            name="char-lora",
            kind="lora",
            identity_bearing=True,
            base_model="flux1-dev",
            metadata={"trigger": "ohwx"},
        )
    )
    listed = reg.list_models()
    assert {a.name for a in listed} == {"flux1-dev", "char-lora"}

    lora = reg.get_model("char-lora")
    assert lora is not None
    assert lora.kind == "lora"
    assert lora.identity_bearing is True
    assert lora.base_model == "flux1-dev"
    assert lora.metadata == {"trigger": "ohwx"}


def test_identity_bearing_persists_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "models.json"
    ModelRegistry(path=path).add(_asset("char-lora", kind="lora", identity_bearing=True))
    # A fresh instance reads the same file from disk.
    reloaded = ModelRegistry(path=path).get_model("char-lora")
    assert reloaded is not None and reloaded.identity_bearing is True


def test_add_upserts_by_name(tmp_path: Path) -> None:
    reg = ModelRegistry(path=tmp_path / "models.json")
    reg.add(_asset("char-lora", kind="lora", identity_bearing=False))
    reg.add(_asset("char-lora", kind="lora", identity_bearing=True))
    listed = reg.list_models()
    assert len(listed) == 1
    assert listed[0].identity_bearing is True


def test_replace_overwrites_wholesale(tmp_path: Path) -> None:
    reg = ModelRegistry(path=tmp_path / "models.json")
    reg.add(_asset("flux1-dev"))
    reg.add(_asset("sdxl-base"))
    reg.replace([_asset("wan2.2")])
    assert [a.name for a in reg.list_models()] == ["wan2.2"]


def test_add_creates_parent_dirs(tmp_path: Path) -> None:
    reg = ModelRegistry(path=tmp_path / "nested" / "deeper" / "models.json")
    reg.add(_asset("flux1-dev"))
    assert (tmp_path / "nested" / "deeper" / "models.json").exists()


def test_default_path_under_agent_data_dir() -> None:
    # fake_env points AGENT_DATA_DIR at a tmp path; the default lands beneath it.
    reg = ModelRegistry()
    assert reg.path.name == "models.json"
    assert reg.path.parent.name == "visual-generation"
    assert "agent-data" in str(reg.path)
