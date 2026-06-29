from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from visual_generation.batch_file import read_batch
from visual_generation.models import LoraRef, ModelAsset, VisualGeneration, WorkflowTemplate
from visual_generation.retrieval import RetrievedContext


def _template(name: str, slots: set[str]) -> WorkflowTemplate:
    return WorkflowTemplate(
        name=name, descriptor="d", graph={},
        slot_map={s: {"node_id": "1", "input_key": s} for s in slots},
    )


# A craft response that INVENTS a recipe and REWRITES the prompt — revise enforcement
# must override everything except the prompt, inheriting the parent's recipe verbatim.
_INVENTED_JSON = """\
{
  "prompt": "a felt puppet wolf, soft studio lighting, shallow depth of field, now with a warm smile",
  "negative_prompt": null,
  "settings": {"steps": 25, "cfg": 3.5, "sampler": "euler"},
  "model": "wrong-model.safetensors",
  "seed_strategy": "random",
  "seed": 7,
  "width": 512,
  "height": 512,
  "lora_stack": [{"name": "invented.safetensors", "strength": 1.0}],
  "rationale": "Gave her a warmer smile."
}"""


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


def _parent_gen(**overrides) -> VisualGeneration:
    base = dict(
        caption="c",
        prompt="a felt puppet wolf, soft studio lighting, shallow depth of field",
        model="z.safetensors",
        lora_stack=[LoraRef(name="felt.safetensors", strength=0.7)],
        settings={"steps": 8, "cfg": 1.0, "sampler": "res_multistep", "scheduler": "simple"},
        seed=4471,
        width=1024,
        height=1216,
        workflow_ref="visual-workflow",
        project="celeste",
    )
    base.update(overrides)
    return VisualGeneration(**base)


def _store(parent: VisualGeneration | None, template: WorkflowTemplate | None, models) -> MagicMock:
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.get_generation = AsyncMock(return_value=parent)
    store.get_template_by_name = AsyncMock(return_value=template)
    store.list_models = MagicMock(return_value=models)
    by_name = {m.name: m for m in models}
    store.get_model = lambda name: by_name.get(name)
    return store


def _patch_retrieve(monkeypatch, ctx: RetrievedContext) -> None:
    import importlib

    draft_mod = importlib.import_module("visual_generation.draft")
    monkeypatch.setattr(draft_mod, "retrieve_context", AsyncMock(return_value=ctx))


def test_redraft_inherits_recipe_and_revises_prompt_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from visual_generation.draft import redraft_sync

    _patch_retrieve(monkeypatch, RetrievedContext())
    parent = _parent_gen()
    template = _template("visual-workflow", {"positive", "steps", "cfg"})  # txt2img, no negative slot
    models = [
        ModelAsset(name="z.safetensors", kind="checkpoint"),
        ModelAsset(name="felt.safetensors", kind="lora", identity_bearing=True),
    ]
    store = _store(parent, template, models)

    out = tmp_path / "celeste.batch.md"
    result = redraft_sync(
        "gen-parent", "give the wolf a warm smile",
        batch_path=out, store=store, memory_store=MagicMock(),
        llm_provider=_fake_provider(_INVENTED_JSON),
    )

    spec = result.spec
    assert result.status == "completed"
    # Recipe inherited from the parent — the invented values are overridden.
    assert spec.seed == 4471
    assert spec.seed_strategy == "fixed"
    assert spec.settings == {"steps": 8, "cfg": 1.0, "sampler": "res_multistep", "scheduler": "simple"}
    assert spec.model == "z.safetensors"
    assert spec.lora_stack == [LoraRef(name="felt.safetensors", strength=0.7)]
    assert spec.width == 1024
    assert spec.height == 1216
    assert spec.workflow_ref == "visual-workflow"
    # Only the prompt is model-authored.
    assert spec.prompt.endswith("now with a warm smile")
    # Lineage is recorded as a revise, NOT as an img2img source.
    assert spec.revised_from == "gen-parent"
    assert spec.source is None
    # Identity re-derived from the registry (parent's LoRA is identity-bearing).
    assert spec.identity_bearing is True
    # Persisted to the batch file with the inherited recipe intact.
    batch = read_batch(out)
    assert batch.specs[0].seed == 4471
    assert batch.specs[0].source is None
    assert batch.specs[0].revised_from == "gen-parent"


def test_redraft_folds_parent_notes_into_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from visual_generation.draft import redraft_sync

    _patch_retrieve(monkeypatch, RetrievedContext())
    parent = _parent_gen(
        notes="next time make her smile warmer",
        context="the neutral expression read as cold",
    )
    template = _template("visual-workflow", {"positive", "steps", "cfg"})
    store = _store(parent, template, [ModelAsset(name="z.safetensors", kind="checkpoint")])
    provider = _fake_provider(_INVENTED_JSON)

    redraft_sync(
        "gen-parent", "warmer smile", batch_path=tmp_path / "p.batch.md",
        store=store, memory_store=MagicMock(), llm_provider=provider,
    )

    _, kwargs = provider.complete.call_args
    user_msg = kwargs["user_text"]
    # notes is the first consumer anywhere; context rides along too.
    assert "next time make her smile warmer" in user_msg
    assert "the neutral expression read as cold" in user_msg
    # The parent's prose is the revise anchor.
    assert parent.prompt in user_msg


def test_redraft_parent_not_found_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from visual_generation.draft import redraft_sync

    store = _store(parent=None, template=None, models=[])
    result = redraft_sync(
        "missing", "warmer smile", batch_path=tmp_path / "p.batch.md",
        store=store, memory_store=MagicMock(), llm_provider=_fake_provider(_INVENTED_JSON),
    )
    assert result.status == "failed"
    assert any("not found" in w for w in result.revise_warnings)


def test_redraft_warns_when_parent_was_img2img(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from visual_generation.draft import redraft_sync

    _patch_retrieve(monkeypatch, RetrievedContext())
    parent = _parent_gen(source_image_path="/tmp/init.png")
    template = _template("visual-workflow", {"positive", "steps", "cfg"})
    store = _store(parent, template, [ModelAsset(name="z.safetensors", kind="checkpoint")])

    result = redraft_sync(
        "gen-parent", "warmer smile", batch_path=tmp_path / "p.batch.md",
        store=store, memory_store=MagicMock(), llm_provider=_fake_provider(_INVENTED_JSON),
    )
    # Still succeeds (text2img revise), but advises the parent was an edit.
    assert result.status == "completed"
    assert any("img2img" in w for w in result.revise_warnings)


def test_redraft_unresolvable_template_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from visual_generation.draft import redraft_sync

    _patch_retrieve(monkeypatch, RetrievedContext())
    parent = _parent_gen(workflow_ref="ghost-template")
    store = _store(parent, template=None, models=[ModelAsset(name="z.safetensors", kind="checkpoint")])

    result = redraft_sync(
        "gen-parent", "warmer smile", batch_path=tmp_path / "p.batch.md",
        store=store, memory_store=MagicMock(), llm_provider=_fake_provider(_INVENTED_JSON),
    )
    assert result.status == "failed"
    assert any("can't preserve the recipe" in w for w in result.revise_warnings)
