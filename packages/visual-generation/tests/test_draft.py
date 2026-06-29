from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from visual_generation.batch_file import read_batch
from visual_generation.models import (
    LoraRef,
    ModelAsset,
    TechniqueLesson,
    VisualGeneration,
    VisualSource,
    WorkflowTemplate,
)
from visual_generation.retrieval import RetrievedContext


def _template(name: str, slots: set[str]) -> WorkflowTemplate:
    """A slot-explicit template — the inert-inheritance advisory only reads slot_map."""
    return WorkflowTemplate(
        name=name, descriptor="d", graph={},
        slot_map={s: {"node_id": "1", "input_key": s} for s in slots},
    )


def _crafted(**overrides) -> dict:
    base = dict(
        prompt="a cinematic wolf in neon rain",
        negative_prompt=None,
        settings={"steps": 20, "cfg": 1.0, "flux_guidance": 3.5},
        model="flux1-dev.safetensors",
        seed_strategy="fixed",
        seed=42,
        width=1024,
        height=1024,
        lora_stack=[],
        rationale="Flux runs CFG≈1.0; guidance 3.5 keeps it crisp.",
    )
    base.update(overrides)
    return base


def _store(flux_template, models) -> MagicMock:
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.get_template_by_name = AsyncMock(return_value=flux_template)
    store.list_models = MagicMock(return_value=models)
    by_name = {m.name: m for m in models}
    store.get_model = lambda name: by_name.get(name)
    return store


def _patch_chain(monkeypatch, ctx: RetrievedContext, crafted: dict) -> None:
    # NB: the `draft` FUNCTION exported in __init__ shadows the `draft` submodule for
    # both dotted-string targets and `import ... as` (which uses attribute access), so
    # fetch the real module from sys.modules via importlib and patch its globals.
    import importlib

    draft_mod = importlib.import_module("visual_generation.draft")
    monkeypatch.setattr(draft_mod, "retrieve_context", AsyncMock(return_value=ctx))
    monkeypatch.setattr(draft_mod, "craft_spec", AsyncMock(return_value=crafted))


def test_draft_appends_spec_and_surfaces_lessons(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, flux_template
) -> None:
    from visual_generation.draft import draft_sync

    ctx = RetrievedContext(
        technique_lessons=[
            (0.9, TechniqueLesson(statement="CFG>7 washes skin on flux1-dev.",
                                  valence="negative", scope="settings", confirmed=True))
        ]
    )
    _patch_chain(monkeypatch, ctx, _crafted())
    store = _store(flux_template, [ModelAsset(name="flux1-dev.safetensors", kind="checkpoint")])

    out = tmp_path / "p.batch.md"
    result = draft_sync(
        "a wolf in neon rain", batch_path=out, template_name="flux-txt2img",
        project="proj", store=store, memory_store=MagicMock(), llm_provider=MagicMock(),
    )

    # Spec appended to the batch file.
    batch = read_batch(out)
    assert len(batch.specs) == 1
    assert batch.specs[0].prompt == "a cinematic wolf in neon rain"
    assert batch.specs[0].workflow_ref == "flux-txt2img"
    # Own technique lesson surfaced inline.
    assert any("washes skin" in n for n in result.tutor_notes)
    # Missing required models advised (template needs ae/t5xxl/clip_l; registry has only flux1-dev).
    assert "ae.safetensors" in result.missing_models
    # Strong local context → no research offer.
    assert result.research_offer is None


def test_draft_offers_research_on_a_gap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, flux_template
) -> None:
    from visual_generation.draft import draft_sync

    _patch_chain(monkeypatch, RetrievedContext(), _crafted())  # empty context → gap
    store = _store(flux_template, [])

    result = draft_sync(
        "an esoteric WAN VACE control trick", batch_path=tmp_path / "p.batch.md",
        template_name="flux-txt2img", store=store, memory_store=MagicMock(), llm_provider=MagicMock(),
    )
    # Gap → research is OFFERED (the topic), never run here.
    assert result.research_offer == "an esoteric WAN VACE control trick"


def test_draft_prefills_identity_from_registry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, flux_template
) -> None:
    from visual_generation.draft import draft_sync

    crafted = _crafted(lora_stack=[{"name": "char-lora.safetensors", "strength": 0.8}])
    _patch_chain(monkeypatch, RetrievedContext(
        technique_lessons=[(0.9, TechniqueLesson(statement="x", valence="positive", confirmed=True))]
    ), crafted)
    store = _store(flux_template, [
        ModelAsset(name="flux1-dev.safetensors", kind="checkpoint"),
        ModelAsset(name="char-lora.safetensors", kind="lora", identity_bearing=True),
    ])

    result = draft_sync(
        "portrait", batch_path=tmp_path / "p.batch.md", template_name="flux-txt2img",
        store=store, memory_store=MagicMock(), llm_provider=MagicMock(),
    )
    # The honest pre-fill derives identity from the registry's LoRA flag.
    assert result.spec.identity_bearing is True


def test_draft_applies_and_surfaces_canon(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, flux_template
) -> None:
    from visual_generation.draft import draft_sync

    _patch_chain(monkeypatch, RetrievedContext(), _crafted(prompt="the narrator on a roof"))
    # Stub the deterministic canon step to a known transform to verify the wiring +
    # persistence (enforce_canon itself is unit-tested in test_canon.py).
    import importlib

    draft_mod = importlib.import_module("visual_generation.draft")
    monkeypatch.setattr(
        draft_mod, "enforce_canon",
        lambda prompt, project, **kw: (f"{prompt}, LOCKED-HAIR", ["injected canon for 'the narrator'"]),
    )
    store = _store(flux_template, [ModelAsset(name="flux1-dev.safetensors", kind="checkpoint")])

    out = tmp_path / "celeste.batch.md"
    result = draft_sync(
        "the narrator on a roof", batch_path=out, template_name="flux-txt2img",
        project="celeste", store=store, memory_store=MagicMock(), llm_provider=MagicMock(),
    )

    assert "LOCKED-HAIR" in result.spec.prompt
    assert result.canon_applied == ["injected canon for 'the narrator'"]
    # The enforced prompt is what gets persisted to the batch file.
    batch = read_batch(out)
    assert "LOCKED-HAIR" in batch.specs[0].prompt


# ── Part 1.5: compile project docs into the draft input ──────────────────────


def _seed_project(base: Path, **docs: str) -> Path:
    folder = base / "celeste"
    folder.mkdir(parents=True)
    for name, text in docs.items():
        (folder / f"{name}.md").write_text(text, encoding="utf-8")
    return folder


def test_draft_compiles_project_docs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, flux_template
) -> None:
    from visual_generation.draft import draft_sync
    import importlib

    draft_mod = importlib.import_module("visual_generation.draft")
    retr = AsyncMock(return_value=RetrievedContext())
    craft = AsyncMock(return_value=_crafted())
    monkeypatch.setattr(draft_mod, "retrieve_context", retr)
    monkeypatch.setattr(draft_mod, "craft_spec", craft)

    projects = tmp_path / "projects"
    _seed_project(
        projects,
        directed="## Rooftop\nThe narrator on a rooftop, neon below.\n\n## Aftermath\nrain\n",
        brief="A neon-noir short.",
    )
    store = _store(flux_template, [ModelAsset(name="flux1-dev.safetensors", kind="checkpoint")])

    result = draft_sync(
        None, points=["wide shot"], scene="rooftop", project="celeste",
        projects_dir=projects, batch_path=tmp_path / "o.batch.md",
        template_name="flux-txt2img", store=store, memory_store=MagicMock(),
        llm_provider=MagicMock(),
    )

    assert "directed.md (scene: rooftop)" in result.compiled_from
    assert "brief.md" in result.compiled_from
    # craft received the compiled brief (key points + doc content).
    compiled_text = craft.call_args.args[0]
    assert "wide shot" in compiled_text
    assert "neon below" in compiled_text
    # retrieval queried the short key points, not the whole doc.
    query = retr.call_args.args[0]
    assert "wide shot" in query
    assert "neon below" not in query


def test_draft_fails_when_nothing_to_compile(tmp_path: Path) -> None:
    from visual_generation.draft import draft_sync

    store = MagicMock()
    store.ensure_collection = AsyncMock()
    result = draft_sync(
        None, project=None, batch_path=tmp_path / "o.batch.md",
        store=store, memory_store=MagicMock(), llm_provider=MagicMock(),
    )
    assert result.status == "failed"
    assert any("Nothing to draft" in w for w in result.revise_warnings)


def test_batch_project_compiles_each_scene(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, flux_template
) -> None:
    from visual_generation.draft import batch_project_sync
    import importlib

    draft_mod = importlib.import_module("visual_generation.draft")
    monkeypatch.setattr(draft_mod, "retrieve_context", AsyncMock(return_value=RetrievedContext()))
    monkeypatch.setattr(draft_mod, "craft_spec", AsyncMock(return_value=_crafted()))

    projects = tmp_path / "projects"
    _seed_project(projects, directed="## Rooftop\nneon\n\n## Aftermath\nrain\n")
    store = _store(flux_template, [ModelAsset(name="flux1-dev.safetensors", kind="checkpoint")])

    out = tmp_path / "celeste.batch.md"
    results = batch_project_sync(
        "celeste", projects_dir=projects, batch_path=out,
        store=store, memory_store=MagicMock(), llm_provider=MagicMock(),
    )

    assert len(results) == 2  # one per scene
    batch = read_batch(out)
    assert len(batch.specs) == 2


def test_batch_project_anchors_every_scene_as_img2img(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, flux_template
) -> None:
    """An anchored batch makes every scene a refinement from one source frame."""
    from visual_generation.draft import batch_project_sync
    import importlib

    draft_mod = importlib.import_module("visual_generation.draft")
    monkeypatch.setattr(draft_mod, "retrieve_context", AsyncMock(return_value=RetrievedContext()))
    monkeypatch.setattr(draft_mod, "craft_spec", AsyncMock(return_value=_crafted()))

    projects = tmp_path / "projects"
    _seed_project(projects, directed="## Rooftop\nneon\n\n## Aftermath\nrain\n")
    store = _store(flux_template, [ModelAsset(name="flux1-dev.safetensors", kind="checkpoint")])
    store.get_generation = AsyncMock(
        return_value=VisualGeneration(caption="anchor still", project="celeste")
    )

    out = tmp_path / "celeste.batch.md"
    results = batch_project_sync(
        "celeste", projects_dir=projects, batch_path=out,
        source=VisualSource(from_generation="gen-anchor"), denoise=0.6,
        template_name="flux-txt2img",
        store=store, memory_store=MagicMock(), llm_provider=MagicMock(),
    )

    assert len(results) == 2
    # Every scene carries the same anchor source and the explicit denoise.
    for r in results:
        assert r.spec.source is not None
        assert r.spec.source.from_generation == "gen-anchor"
        assert r.spec.settings["denoise"] == 0.6


def _refinement_store(template: WorkflowTemplate, parent: VisualGeneration | None) -> MagicMock:
    store = _store(template, [ModelAsset(name="z.safetensors", kind="checkpoint")])
    store.get_generation = AsyncMock(return_value=parent)
    return store


def test_draft_warns_inherited_lora_and_dims_template_lacks_slots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from visual_generation.draft import draft_sync

    crafted = _crafted(
        lora_stack=[{"name": "felt.safetensors", "strength": 0.7}], width=832, height=1216,
    )
    _patch_chain(monkeypatch, RetrievedContext(), crafted)
    parent = VisualGeneration(caption="c", lora_stack=[], width=832, height=1216)
    # img2img-style template: no LoRA loader slot, no width/height slots.
    template = _template("z-img2img", {"positive", "init_image", "steps", "denoise"})
    store = _refinement_store(template, parent)

    result = draft_sync(
        "warmer key light", batch_path=tmp_path / "p.batch.md", template_name="z-img2img",
        source=VisualSource(from_generation="gen-p"),
        store=store, memory_store=MagicMock(), llm_provider=MagicMock(),
    )

    assert len(result.inert_inheritance) == 2
    assert any("LoRA" in w for w in result.inert_inheritance)
    assert any("dimensions" in w for w in result.inert_inheritance)


def test_draft_no_warning_when_template_exposes_slots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from visual_generation.draft import draft_sync

    crafted = _crafted(
        lora_stack=[{"name": "felt.safetensors", "strength": 0.7}], width=832, height=1216,
    )
    _patch_chain(monkeypatch, RetrievedContext(), crafted)
    parent = VisualGeneration(caption="c", lora_stack=[], width=832, height=1216)
    template = _template("z-i2i-lora", {"lora_0", "width", "height", "positive", "init_image"})
    store = _refinement_store(template, parent)

    result = draft_sync(
        "warmer key light", batch_path=tmp_path / "p.batch.md", template_name="z-i2i-lora",
        source=VisualSource(from_generation="gen-p"),
        store=store, memory_store=MagicMock(), llm_provider=MagicMock(),
    )

    assert result.inert_inheritance == []


def test_draft_txt2img_has_no_inert_inheritance_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from visual_generation.draft import draft_sync

    # A txt2img draft (no source/parent) carries LoRAs + dims but the gate is off.
    crafted = _crafted(
        lora_stack=[{"name": "felt.safetensors", "strength": 0.7}], width=832, height=1216,
    )
    _patch_chain(monkeypatch, RetrievedContext(), crafted)
    template = _template("txt2img", {"positive", "steps"})  # no lora/dim slots either
    store = _refinement_store(template, parent=None)

    result = draft_sync(
        "a wolf in neon rain", batch_path=tmp_path / "p.batch.md", template_name="txt2img",
        store=store, memory_store=MagicMock(), llm_provider=MagicMock(),
    )

    assert result.inert_inheritance == []


# ── Edit-mode seed-from-parent inheritance (real craft_spec) ──────────────────


def _fake_provider(json_text: str) -> MagicMock:
    """An LLMProvider stand-in whose single completion carries `json_text`."""
    from agent_runtime.llm import LLMCompletion

    prov = MagicMock()
    prov.resolve_model = MagicMock(side_effect=lambda m: m or "claude-sonnet-4-6")
    prov.complete = AsyncMock(
        return_value=LLMCompletion(
            text=json_text, input_tokens=200, output_tokens=80, model="claude-sonnet-4-6"
        )
    )
    return prov


# A craft response that INVENTS a recipe and REWRITES the prompt — exactly what
# edit-mode enforcement must override (settings) / preserve (prompt).
_INVENTED_JSON = """\
{
  "prompt": "warmer key light on the felt puppet, cozy studio glow",
  "negative_prompt": null,
  "settings": {"steps": 25, "cfg": 3.5, "sampler": "euler"},
  "model": "wrong-model.safetensors",
  "seed_strategy": "fixed",
  "seed": 7,
  "width": 1024,
  "height": 1024,
  "lora_stack": [{"name": "invented.safetensors", "strength": 1.0}],
  "rationale": "Bumped steps for detail."
}"""


def _parent_gen() -> VisualGeneration:
    return VisualGeneration(
        caption="c",
        prompt="a felt puppet wolf, soft studio lighting, shallow depth of field",
        model="z.safetensors",
        lora_stack=[LoraRef(name="felt.safetensors", strength=0.7)],
        width=832,
        height=1216,
    )


@pytest.mark.asyncio
async def test_craft_spec_edit_mode_inherits_parent_and_strips_recipe() -> None:
    from visual_generation.chains import craft_spec

    parent = _parent_gen()
    template = _template("z-img2img", {"positive", "init_image", "steps", "denoise"})
    models = [ModelAsset(name="z.safetensors", kind="checkpoint")]
    provider = _fake_provider(_INVENTED_JSON)

    spec = await craft_spec(
        "warmer key light", RetrievedContext(), template, models, provider,
        parent=parent, refinement=True,
    )

    # Invented recipe stripped — the template recipe stands, caller owns denoise.
    assert spec["settings"] == {}
    # Identity-bearing attrs inherited from the parent, not the model's guesses.
    assert spec["model"] == "z.safetensors"
    assert spec["lora_stack"] == [{"name": "felt.safetensors", "strength": 0.7}]
    assert spec["width"] == 832
    assert spec["height"] == 1216
    # The craft's edited prompt is kept (this is an edit, not a no-op).
    assert spec["prompt"] == "warmer key light on the felt puppet, cozy studio glow"
    # The source prompt was anchored into the user message the provider received.
    _, kwargs = provider.complete.call_args
    user_msg = kwargs["user_text"]
    assert parent.prompt in user_msg


def test_draft_from_parent_appends_denoise_only_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from visual_generation.draft import draft_sync

    # Patch ONLY retrieve_context — exercise the real craft_spec + enforcement.
    import importlib

    draft_mod = importlib.import_module("visual_generation.draft")
    monkeypatch.setattr(draft_mod, "retrieve_context", AsyncMock(return_value=RetrievedContext()))

    parent = _parent_gen()
    template = _template("z-img2img", {"positive", "init_image", "steps", "denoise"})
    store = _refinement_store(template, parent)

    out = tmp_path / "p.batch.md"
    result = draft_sync(
        "warmer key light", batch_path=out, template_name="z-img2img",
        source=VisualSource(from_generation="gen-p"), denoise=0.55,
        store=store, memory_store=MagicMock(), llm_provider=_fake_provider(_INVENTED_JSON),
    )

    # Denoise is the ONLY settings key — the invented recipe was stripped first.
    assert result.spec.settings == {"denoise": 0.55}
    assert result.spec.model == "z.safetensors"
    batch = read_batch(out)
    assert batch.specs[0].settings == {"denoise": 0.55}
    assert batch.specs[0].model == "z.safetensors"


@pytest.mark.asyncio
async def test_craft_spec_txt2img_keeps_invented_recipe() -> None:
    from visual_generation.chains import craft_spec

    # No parent, refinement=False → enforcement is gated off, recipe survives.
    template = _template("txt2img", {"positive", "steps", "cfg"})
    models = [ModelAsset(name="wrong-model.safetensors", kind="checkpoint")]
    spec = await craft_spec(
        "a felt puppet wolf", RetrievedContext(), template, models,
        _fake_provider(_INVENTED_JSON),
    )

    assert spec["settings"] == {"steps": 25, "cfg": 3.5, "sampler": "euler"}
    assert spec["model"] == "wrong-model.safetensors"
