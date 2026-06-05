from __future__ import annotations

from pathlib import Path

from voiceover_direction.models import VoiceProfile
from voiceover_direction.voice_registry import VoiceRegistry


def _voice(voice_id: str, name: str, category: str = "stock") -> VoiceProfile:
    return VoiceProfile(voice_id=voice_id, name=name, category=category)  # type: ignore[arg-type]


def test_empty_when_file_absent(tmp_path: Path) -> None:
    reg = VoiceRegistry(path=tmp_path / "voices.json")
    assert reg.list_voices() == []
    assert reg.get_voice("anything") is None


def test_replace_then_list_round_trip(tmp_path: Path) -> None:
    reg = VoiceRegistry(path=tmp_path / "voices.json")
    voices = [
        _voice("v1", "Rachel"),
        VoiceProfile(
            voice_id="v2",
            name="Custom",
            category="cloned",
            labels={"accent": "british"},
            description="my clone",
        ),
    ]
    reg.replace(voices)
    listed = reg.list_voices()
    assert listed == voices


def test_get_voice_hit_and_miss(tmp_path: Path) -> None:
    reg = VoiceRegistry(path=tmp_path / "voices.json")
    reg.replace([_voice("v1", "Rachel"), _voice("v2", "Adam")])
    hit = reg.get_voice("v2")
    assert hit is not None and hit.name == "Adam"
    assert reg.get_voice("nope") is None


def test_replace_overwrites_wholesale(tmp_path: Path) -> None:
    reg = VoiceRegistry(path=tmp_path / "voices.json")
    reg.replace([_voice("v1", "Rachel"), _voice("v2", "Adam")])
    reg.replace([_voice("v3", "New")])
    listed = reg.list_voices()
    assert [v.voice_id for v in listed] == ["v3"]


def test_replace_creates_parent_dirs(tmp_path: Path) -> None:
    reg = VoiceRegistry(path=tmp_path / "nested" / "deeper" / "voices.json")
    reg.replace([_voice("v1", "Rachel")])
    assert (tmp_path / "nested" / "deeper" / "voices.json").exists()


def test_default_path_under_agent_data_dir() -> None:
    # fake_env points AGENT_DATA_DIR at a tmp path; the default lands beneath it.
    reg = VoiceRegistry()
    assert reg.path.name == "voices.json"
    assert reg.path.parent.name == "voiceover"
    assert "agent-data" in str(reg.path)
