from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from click.testing import CliRunner

from visual_generation.cli import cli
from visual_generation.model_registry import ModelRegistry
from visual_generation.models import ModelAsset, WorkflowTemplate


def _object_info() -> dict:
    return {
        "UNETLoader": {"input": {"required": {"unet_name": [["flux1-dev.safetensors"]]}}},
        "LoraLoader": {"input": {"required": {"lora_name": [["char-lora.safetensors"]]}}},
        "VAELoader": {"input": {"required": {"vae_name": [["ae.safetensors"]]}}},
    }


class _FakeClient:
    def __init__(self, endpoint: str, **kwargs) -> None:
        self.endpoint = endpoint

    async def object_info(self) -> dict:
        return _object_info()


# ── model sync / list ────────────────────────────────────────────────────────


def test_model_sync_writes_registry_and_preserves_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("visual_generation.cli.ComfyUIClient", _FakeClient)
    # Pre-register a manual identity-bearing LoRA (present in the pod's object_info).
    reg = ModelRegistry()
    reg.add(ModelAsset(name="char-lora.safetensors", kind="lora", identity_bearing=True,
                       source="registered"))

    result = CliRunner().invoke(cli, ["model", "sync", "--endpoint", "http://pod:8188", "--yes"])
    assert result.exit_code == 0, result.output

    after = {a.name: a for a in ModelRegistry().list_models()}
    # New assets synced in.
    assert "flux1-dev.safetensors" in after
    assert "ae.safetensors" in after
    # Manual identity_bearing survived the sync (merge).
    assert after["char-lora.safetensors"].identity_bearing is True
    assert after["char-lora.safetensors"].source == "registered"


def test_model_sync_unreachable_endpoint_is_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    from visual_generation.comfyui_client import ComfyUIUnreachable

    class _Down:
        def __init__(self, endpoint: str, **kwargs) -> None:
            pass

        async def object_info(self) -> dict:
            raise ComfyUIUnreachable("ComfyUI endpoint unreachable at http://pod:8188")

    monkeypatch.setattr("visual_generation.cli.ComfyUIClient", _Down)
    result = CliRunner().invoke(cli, ["model", "sync", "--endpoint", "http://pod:8188", "--yes"])
    assert result.exit_code != 0
    assert "unreachable" in result.output.lower()


def test_model_list_shows_identity_bearing() -> None:
    reg = ModelRegistry()
    reg.add(ModelAsset(name="char-lora.safetensors", kind="lora", identity_bearing=True))
    reg.add(ModelAsset(name="flux1-dev.safetensors", kind="checkpoint"))

    result = CliRunner().invoke(cli, ["model", "list"])
    assert result.exit_code == 0
    assert "char-lora.safetensors" in result.output
    assert "identity-bearing" in result.output


def test_model_list_empty() -> None:
    result = CliRunner().invoke(cli, ["model", "list"])
    assert result.exit_code == 0
    assert "No models registered" in result.output


# ── workflow register / list ─────────────────────────────────────────────────


def _mock_stores(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.upsert_template = AsyncMock()
    store.search_templates = AsyncMock(return_value=[])
    monkeypatch.setattr("visual_generation.cli._get_stores", lambda: (store, MagicMock()))
    return store


def test_workflow_register_flux_stores_correct_slot_map(
    monkeypatch: pytest.MonkeyPatch, flux_graph_file: Path
) -> None:
    store = _mock_stores(monkeypatch)

    result = CliRunner().invoke(
        cli,
        ["workflow", "register", str(flux_graph_file),
         "--name", "flux-txt2img", "--descriptor", "basic flux still", "--yes"],
    )
    assert result.exit_code == 0, result.output

    template: WorkflowTemplate = store.upsert_template.call_args[0][0]
    assert template.name == "flux-txt2img"
    assert template.slot_map["positive"] == {"node_id": "6", "input_key": "text"}
    assert template.slot_map["flux_guidance"] == {"node_id": "13", "input_key": "guidance"}
    assert "negative" not in template.slot_map  # Flux: suppressed by default
    assert template.required_models == [
        "flux1-dev.safetensors", "ae.safetensors",
        "t5xxl_fp16.safetensors", "clip_l.safetensors",
    ]
    # Advisory: required models not in the (empty) registry are surfaced.
    assert "Not in registry" in result.output


def test_workflow_register_propose_confirm_can_add_negative(
    monkeypatch: pytest.MonkeyPatch, flux_graph_file: Path
) -> None:
    store = _mock_stores(monkeypatch)

    # Interactive (no --yes): answer "y" to add a negative slot, then "y" to accept.
    result = CliRunner().invoke(
        cli,
        ["workflow", "register", str(flux_graph_file), "--descriptor", "d"],
        input="y\ny\n",
    )
    assert result.exit_code == 0, result.output

    template: WorkflowTemplate = store.upsert_template.call_args[0][0]
    # The override mapped the negative slot to the traced empty-text node "7".
    assert template.slot_map["negative"] == {"node_id": "7", "input_key": "text"}


def test_workflow_register_abort_on_reject(
    monkeypatch: pytest.MonkeyPatch, flux_graph_file: Path
) -> None:
    store = _mock_stores(monkeypatch)
    # Decline the negative-add (n), then reject the slot map (n) → abort, no store write.
    result = CliRunner().invoke(
        cli,
        ["workflow", "register", str(flux_graph_file), "--descriptor", "d"],
        input="n\nn\n",
    )
    assert result.exit_code != 0
    store.upsert_template.assert_not_called()


def test_workflow_register_rejects_non_graph_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _mock_stores(monkeypatch)
    bad = tmp_path / "bad.json"
    bad.write_text("[1, 2, 3]", encoding="utf-8")
    result = CliRunner().invoke(cli, ["workflow", "register", str(bad), "--yes", "--descriptor", "d"])
    assert result.exit_code != 0
    assert "API-format graph" in result.output


def test_workflow_list_renders(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _mock_stores(monkeypatch)
    tmpl = WorkflowTemplate(
        name="flux-txt2img", descriptor="basic flux still",
        slot_map={"positive": {"node_id": "6", "input_key": "text"}},
        required_models=["flux1-dev.safetensors"],
    )
    store.search_templates = AsyncMock(return_value=[(tmpl.entry_id, 0.9, tmpl)])

    result = CliRunner().invoke(cli, ["workflow", "list"])
    assert result.exit_code == 0
    assert "flux-txt2img" in result.output
    assert "flux1-dev.safetensors" in result.output


# ── model alias resolution + --model threading ───────────────────────────────


def test_resolve_model_aliases_and_default() -> None:
    from visual_generation.constants import MODEL_DIRECTOR, resolve_model

    assert resolve_model(None) == MODEL_DIRECTOR          # omitted → sonnet
    assert resolve_model("sonnet") == MODEL_DIRECTOR
    assert resolve_model("opus") == "claude-opus-4-8"


def test_draft_threads_model_alias_to_draft_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def _fake_draft_sync(intent, **kwargs):
        captured.update(kwargs)
        captured["intent"] = intent
        from visual_generation.models import DraftResult, VisualSpec
        return DraftResult(spec=VisualSpec(prompt="p", heading="h"), status="completed")

    monkeypatch.setattr("visual_generation.cli.draft_sync", _fake_draft_sync)
    result = CliRunner().invoke(cli, ["draft", "a wolf", "--model", "opus"])
    assert result.exit_code == 0
    assert captured["model"] == "opus"


def test_redraft_threads_model_alias_to_redraft_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def _fake_redraft_sync(gen_id, change, **kwargs):
        captured["gen_id"] = gen_id
        captured["change"] = change
        captured.update(kwargs)
        from visual_generation.models import DraftResult, VisualSpec
        return DraftResult(
            spec=VisualSpec(prompt="p", heading="h", revised_from=gen_id, workflow_ref="w"),
            status="completed", template_name="w",
        )

    monkeypatch.setattr("visual_generation.cli.redraft_sync", _fake_redraft_sync)
    result = CliRunner().invoke(cli, ["redraft", "gen-1", "warmer smile", "--model", "sonnet"])
    assert result.exit_code == 0
    assert captured["gen_id"] == "gen-1"
    assert captured["change"] == "warmer smile"
    assert captured["model"] == "sonnet"


def test_redraft_reports_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_redraft_sync(gen_id, change, **kwargs):
        from visual_generation.models import DraftResult, VisualSpec
        return DraftResult(
            spec=VisualSpec(prompt="", heading=""), status="failed",
            revise_warnings=["generation gen-x not found in memory."],
        )

    monkeypatch.setattr("visual_generation.cli.redraft_sync", _fake_redraft_sync)
    result = CliRunner().invoke(cli, ["redraft", "gen-x", "warmer smile"])
    assert result.exit_code != 0
    assert "not found" in result.output


# ── batch list / rm ──────────────────────────────────────────────────────────


def _batch_file(tmp_path: Path) -> Path:
    from visual_generation.batch_file import write_batch
    from visual_generation.models import GenerationBatch, VisualSpec

    batch = GenerationBatch(
        project="proj",
        specs=[
            VisualSpec(heading="one", prompt="first", workflow_ref="flux-txt2img"),
            VisualSpec(heading="two", prompt="second", workflow_ref="flux-txt2img"),
            VisualSpec(heading="three", prompt="third", workflow_ref="flux-txt2img"),
        ],
    )
    path = tmp_path / "p.batch.md"
    write_batch(batch, path)
    return path


def test_batch_list_shows_spec_ids_and_titles(tmp_path: Path) -> None:
    from visual_generation.batch_file import read_batch

    path = _batch_file(tmp_path)
    ids = [s.spec_id for s in read_batch(path).specs]
    result = CliRunner().invoke(cli, ["batch", "list", str(path)])
    assert result.exit_code == 0
    assert "3 spec(s)" in result.output
    for sid in ids:
        assert sid in result.output
    assert "one" in result.output and "flux-txt2img" in result.output


def test_batch_rm_removes_only_the_target(tmp_path: Path) -> None:
    from visual_generation.batch_file import read_batch

    path = _batch_file(tmp_path)
    before = read_batch(path).specs
    target = before[1]
    survivors = [before[0], before[2]]

    result = CliRunner().invoke(cli, ["batch", "rm", str(path), target.spec_id, "--yes"])
    assert result.exit_code == 0

    after = read_batch(path).specs
    assert [s.spec_id for s in after] == [s.spec_id for s in survivors]
    # The survivors are unchanged (same specs, byte-for-byte through the round-trip).
    assert after == survivors


def test_batch_rm_unknown_id_errors(tmp_path: Path) -> None:
    path = _batch_file(tmp_path)
    result = CliRunner().invoke(cli, ["batch", "rm", str(path), "no-such-id", "--yes"])
    assert result.exit_code != 0
    assert "No spec with id" in result.output
