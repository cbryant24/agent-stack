from __future__ import annotations

from pathlib import Path

from visual_generation.batch_file import append_spec, read_batch, write_batch
from visual_generation.models import GenerationBatch, LoraRef, VisualSpec


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
