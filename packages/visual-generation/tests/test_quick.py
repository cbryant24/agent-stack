from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from visual_generation.comfyui_client import ComfyUIClient
from visual_generation.quick import (
    QuickSeedUnmapped,
    QuickSourceError,
    QuickTemplateNotFound,
    quick_generate_sync,
)


class _FakeComfy:
    """A ComfyUI client double: records submits/uploads, returns one media item."""

    def __init__(self, *, video: bool = False) -> None:
        self.submitted: list[dict] = []
        self.uploads: list[tuple[str, bytes]] = []
        self._video = video

    async def submit(self, graph: dict, client_id=None) -> str:
        self.submitted.append(graph)
        return "pid-1"

    async def history(self, prompt_id: str) -> dict:
        if self._video:
            return {"outputs": {"80": {
                "videos": [{"filename": "out.mp4", "subfolder": "", "type": "output"}]
            }}}
        return {"outputs": {"9": {
            "images": [{"filename": "out.png", "subfolder": "", "type": "output"}]
        }}}

    async def view(self, filename, subfolder="", type="output") -> bytes:
        return b"FAKEVIDEO" if self._video else b"\x89PNGdata"

    async def upload_image(self, data: bytes, filename: str, *, subfolder="", overwrite=True) -> str:
        self.uploads.append((filename, data))
        return f"input/{filename}"

    images_from_history = staticmethod(ComfyUIClient.images_from_history)
    videos_from_history = staticmethod(ComfyUIClient.videos_from_history)


def _store(template) -> MagicMock:
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.get_template_by_name = AsyncMock(return_value=template)
    return store


# ── stills ─────────────────────────────────────────────────────────────────


def test_quick_still_round_trip_writes_asset_and_no_memory(flux_template) -> None:
    store = _store(flux_template)
    fake = _FakeComfy()

    result = quick_generate_sync(
        "a wolf in neon rain",
        endpoint="http://pod:8188",
        template_name="flux-txt2img",
        seed=42,
        store=store,
        client=fake,
    )

    assert fake.submitted[0]["6"]["inputs"]["text"] == "a wolf in neon rain"
    assert result.seed == 42
    assert result.video is False
    assert result.asset_path.exists()
    assert result.asset_path.suffix == ".png"
    assert "/assets/adhoc/" in str(result.asset_path)
    # The actual "separate from the pipeline" contract: nothing written to memory.
    store.upsert_generation.assert_not_called()


def test_quick_random_seed_when_none_given(flux_template) -> None:
    result = quick_generate_sync(
        "x", endpoint="x", template_name="flux-txt2img",
        store=_store(flux_template), client=_FakeComfy(),
    )
    assert isinstance(result.seed, int)


def test_quick_writes_to_explicit_out_path(flux_template, tmp_path: Path) -> None:
    out = tmp_path / "somewhere" / "pic.png"
    result = quick_generate_sync(
        "x", endpoint="x", template_name="flux-txt2img", out_path=str(out),
        store=_store(flux_template), client=_FakeComfy(),
    )
    assert result.asset_path == out
    assert out.read_bytes() == b"\x89PNGdata"


def test_quick_raises_when_template_missing() -> None:
    store = _store(None)
    with pytest.raises(QuickTemplateNotFound, match="not-registered"):
        quick_generate_sync(
            "x", endpoint="x", template_name="not-registered",
            store=store, client=_FakeComfy(),
        )


# ── video (WAN 2.2 T2V / I2V) ─────────────────────────────────────────────


def test_quick_video_round_trip_produces_mp4(wan_t2v_template) -> None:
    store = _store(wan_t2v_template)
    fake = _FakeComfy(video=True)

    result = quick_generate_sync(
        "a red fox running through falling snow",
        endpoint="http://pod:8188",
        video=True,
        template_name="wan2.2-t2v",
        seed=7,
        store=store,
        client=fake,
    )

    assert result.video is True
    assert result.asset_path.suffix == ".mp4"
    assert result.asset_path.read_bytes() == b"FAKEVIDEO"
    # Recipe-locked defaults (length/fps) reached the graph via _SETTING_SLOTS.
    assert fake.submitted[0]["74"]["inputs"]["length"] == 33
    assert fake.submitted[0]["88"]["inputs"]["fps"] == 16
    assert fake.submitted[0]["81"]["inputs"]["noise_seed"] == 7
    store.upsert_generation.assert_not_called()


def test_quick_video_length_and_fps_overrides(wan_t2v_template) -> None:
    fake = _FakeComfy(video=True)
    quick_generate_sync(
        "x", endpoint="x", video=True, template_name="wan2.2-t2v",
        length=49, fps=24, store=_store(wan_t2v_template), client=fake,
    )
    assert fake.submitted[0]["74"]["inputs"]["length"] == 49
    assert fake.submitted[0]["88"]["inputs"]["fps"] == 24


def test_quick_i2v_uploads_seed_image_and_writes_init_image_slot(
    wan_i2v_template, tmp_path: Path
) -> None:
    seed_img = tmp_path / "still.png"
    seed_img.write_bytes(b"\x89PNGseed")
    fake = _FakeComfy(video=True)

    result = quick_generate_sync(
        "the woman blinks and slowly shifts her weight",
        endpoint="x", video=True, template_name="wan2.2-i2v",
        image_path=str(seed_img), store=_store(wan_i2v_template), client=fake,
    )

    assert fake.uploads == [(f"quick_{seed_img.name}", b"\x89PNGseed")]
    assert fake.submitted[0]["97"]["inputs"]["image"] == f"input/quick_{seed_img.name}"
    assert result.video is True


def test_quick_i2v_missing_seed_file_raises_source_error(wan_i2v_template, tmp_path: Path) -> None:
    with pytest.raises(QuickSourceError):
        quick_generate_sync(
            "x", endpoint="x", video=True, template_name="wan2.2-i2v",
            image_path=str(tmp_path / "does-not-exist.png"),
            store=_store(wan_i2v_template), client=_FakeComfy(video=True),
        )


def test_quick_image_against_template_with_no_init_image_slot_raises(flux_template, tmp_path: Path) -> None:
    seed_img = tmp_path / "still.png"
    seed_img.write_bytes(b"x")
    with pytest.raises(QuickSourceError, match="no init_image slot"):
        quick_generate_sync(
            "x", endpoint="x", template_name="flux-txt2img", image_path=str(seed_img),
            store=_store(flux_template), client=_FakeComfy(),
        )


# ── unmapped values ────────────────────────────────────────────────────────


def test_quick_returns_unmapped_values_on_the_result(flux_template) -> None:
    # Flux has no negative slot: the render proceeds, but the miss is reported.
    fake = _FakeComfy()
    result = quick_generate_sync(
        "x", endpoint="x", template_name="flux-txt2img", negative_prompt="blurry",
        store=_store(flux_template), client=fake,
    )
    assert result.unmapped == ["negative"]
    assert len(fake.submitted) == 1


def test_quick_with_no_unmapped_values_reports_an_empty_list(flux_template) -> None:
    result = quick_generate_sync(
        "x", endpoint="x", template_name="flux-txt2img",
        store=_store(flux_template), client=_FakeComfy(),
    )
    assert result.unmapped == []


def test_quick_refuses_when_the_template_has_no_seed_slot(flux_template) -> None:
    template = flux_template.model_copy(
        update={"slot_map": {k: v for k, v in flux_template.slot_map.items() if k != "seed"}}
    )
    fake = _FakeComfy()
    with pytest.raises(QuickSeedUnmapped, match="no seed slot"):
        quick_generate_sync(
            "x", endpoint="x", template_name="flux-txt2img", seed=5,
            store=_store(template), client=fake,
        )
    assert fake.submitted == []  # nothing reached the pod
