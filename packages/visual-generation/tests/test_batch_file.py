from __future__ import annotations

from pathlib import Path

import pytest

from visual_generation.batch_file import (
    append_spec,
    read_batch,
    remove_spec,
    replace_spec,
    write_batch,
)
from visual_generation.models import GenerationBatch, LoraRef, VisualSource, VisualSpec


def _spec(heading: str, prompt: str, **overrides) -> VisualSpec:
    base = dict(
        heading=heading,
        prompt=prompt,
        settings={"steps": 20, "cfg": 1.0, "flux_guidance": 3.5},
        model="flux1-dev.safetensors",
        seed=42,
        width=1024,
        height=1024,
        workflow_ref="flux-txt2img",
        project="proj",
    )
    base.update(overrides)
    return VisualSpec(**base)


def test_round_trip_multiple_specs(tmp_path: Path) -> None:
    batch = GenerationBatch(
        project="proj",
        specs=[
            _spec("wolf", "a wolf in neon rain"),
            _spec("city", "a rain-slicked city", lora_stack=[LoraRef(name="x.safetensors", strength=0.7)]),
        ],
    )
    path = tmp_path / "p.batch.md"
    write_batch(batch, path)
    restored = read_batch(path)

    assert restored == batch  # lossless round-trip


def test_source_block_round_trips(tmp_path: Path) -> None:
    # A refinement spec (img2img from a prior generation, with mask) round-trips.
    batch = GenerationBatch(
        project="proj",
        specs=[
            _spec(
                "warmer light",
                "warmer key light",
                settings={"denoise": 0.55},
                source=VisualSource(from_generation="gen-abc", mask="/tmp/mask.png"),
            ),
            _spec(
                "from ref",
                "in the style of",
                source=VisualSource(image_path="/tmp/ref.png"),
            ),
        ],
    )
    path = tmp_path / "p.batch.md"
    write_batch(batch, path)
    restored = read_batch(path)
    assert restored == batch
    assert restored.specs[0].source.from_generation == "gen-abc"
    assert restored.specs[0].source.mask == "/tmp/mask.png"
    assert restored.specs[1].source.image_path == "/tmp/ref.png"


def test_flf2v_and_edit_source_fields_round_trip(tmp_path: Path) -> None:
    # FLF2V (first + last frame) and Qwen edit (base + ordered references) round-trip.
    from visual_generation.models import RefImage

    batch = GenerationBatch(
        project="short-film",
        specs=[
            _spec(
                "clip 1", "narrator walks in", workflow_ref="wan22-flf2v",
                settings={"length": 81, "fps": 16},
                source=VisualSource(from_generation="genA", last_from_generation="genB"),
            ),
            _spec(
                "keyframe edit", "same shot, new pose", workflow_ref="qwen-edit-2511",
                source=VisualSource(
                    from_generation="genBase",
                    references=[RefImage(from_generation="idSheet"),
                                RefImage(image_path="/tmp/outfit.png")],
                ),
            ),
        ],
    )
    path = tmp_path / "seq.batch.md"
    write_batch(batch, path)
    restored = read_batch(path)
    assert restored == batch  # lossless round-trip
    assert restored.specs[0].source.last_from_generation == "genB"
    assert restored.specs[1].source.references[1].image_path == "/tmp/outfit.png"


def test_prompt_is_the_body_not_duplicated(tmp_path: Path) -> None:
    batch = GenerationBatch(specs=[_spec("wolf", "a wolf in neon rain")])
    path = tmp_path / "p.batch.md"
    write_batch(batch, path)
    raw = path.read_text(encoding="utf-8")
    # The prompt appears once, as the body — not inside the vg-spec JSON.
    assert raw.count("a wolf in neon rain") == 1
    assert '"prompt"' not in raw


def test_append_spec_creates_then_grows(tmp_path: Path) -> None:
    path = tmp_path / "p.batch.md"
    append_spec(path, _spec("one", "first"), project="proj")
    append_spec(path, _spec("two", "second"), project="proj")
    batch = read_batch(path)
    assert [s.prompt for s in batch.specs] == ["first", "second"]
    assert batch.project == "proj"


def test_write_batch_creates_missing_parent_dir(tmp_path: Path) -> None:
    # KI-6: writing under a not-yet-created batches/ dir must succeed, not crash.
    batch = GenerationBatch(project="proj", specs=[_spec("wolf", "a wolf in neon rain")])
    path = tmp_path / "nonexistent" / "batches" / "p.batch.md"
    assert not path.parent.exists()
    write_batch(batch, path)
    assert path.exists()
    assert read_batch(path) == batch


def test_hand_edited_spec_without_metadata_comment(tmp_path: Path) -> None:
    # A human writes a section with no vg-spec comment — body is read as the prompt.
    path = tmp_path / "hand.batch.md"
    path.write_text(
        '<!-- vg-batch: {"project": "p"} -->\n\n'
        "## hand written\n\n"
        "a lighthouse at dawn\n",
        encoding="utf-8",
    )
    batch = read_batch(path)
    assert len(batch.specs) == 1
    assert batch.specs[0].prompt == "a lighthouse at dawn"
    assert batch.specs[0].heading == "hand written"


def test_malformed_spec_json_degrades_to_defaults(tmp_path: Path) -> None:
    path = tmp_path / "broken.batch.md"
    path.write_text(
        '<!-- vg-batch: {"project": "p"} -->\n\n'
        "## broken meta\n"
        "<!-- vg-spec: {this is not json, oops -->\n\n"
        "a desert highway\n",
        encoding="utf-8",
    )
    batch = read_batch(path)
    assert len(batch.specs) == 1
    spec = batch.specs[0]
    # The prompt body survives; the garbled metadata falls back to defaults.
    assert spec.prompt == "a desert highway"
    assert spec.model is None
    assert spec.settings == {}


def test_malformed_batch_header_degrades(tmp_path: Path) -> None:
    path = tmp_path / "badhdr.batch.md"
    path.write_text("<!-- vg-batch: {nope -->\n\n## s\n\nbody\n", encoding="utf-8")
    batch = read_batch(path)
    assert batch.specs[0].prompt == "body"


def test_remove_spec_drops_only_the_target_and_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "p.batch.md"
    append_spec(path, _spec("one", "first"), project="proj")
    append_spec(path, _spec("two", "second"), project="proj")
    append_spec(path, _spec("three", "third"), project="proj")
    batch = read_batch(path)
    target = batch.specs[1]  # "second"
    # The bytes of the two survivors, captured before removal.
    write_batch(remove_spec(batch, target.spec_id), path)

    restored = read_batch(path)
    assert [s.prompt for s in restored.specs] == ["first", "third"]
    # The survivors' spec_ids are preserved (we removed the right one).
    assert target.spec_id not in {s.spec_id for s in restored.specs}


def test_remove_spec_unknown_id_raises(tmp_path: Path) -> None:
    batch = GenerationBatch(specs=[_spec("one", "first")])
    with pytest.raises(ValueError):
        remove_spec(batch, "no-such-id")


def test_replace_spec_swaps_in_place_preserving_order(tmp_path: Path) -> None:
    batch = GenerationBatch(
        project="proj",
        specs=[_spec("one", "first"), _spec("two", "second"), _spec("three", "third")],
    )
    target_id = batch.specs[1].spec_id
    new = _spec("two-revised", "second, but warmer")
    replace_spec(batch, target_id, new)

    assert [s.prompt for s in batch.specs] == ["first", "second, but warmer", "third"]
    assert batch.specs[1].spec_id == new.spec_id


def test_replace_spec_unknown_id_raises() -> None:
    batch = GenerationBatch(specs=[_spec("one", "first")])
    with pytest.raises(ValueError):
        replace_spec(batch, "no-such-id", _spec("x", "x"))
