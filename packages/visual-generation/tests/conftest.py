from __future__ import annotations

import os
from pathlib import Path

import pytest


def _qdrant_reachable() -> bool:
    try:
        import httpx
        r = httpx.get("http://localhost:6333/healthz", timeout=1.0)
        return r.status_code == 200
    except Exception:
        return False


requires_qdrant = pytest.mark.skipif(
    not _qdrant_reachable(),
    reason="Qdrant not running at localhost:6333",
)


LIVE = os.environ.get("AGENT_SHELL_LIVE") == "1"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "live: calls a real provider (costs money); run with AGENT_SHELL_LIVE=1 under `op run`"
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if LIVE:
        return
    skip = pytest.mark.skip(reason="live provider test: set AGENT_SHELL_LIVE=1 (under op run)")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def fake_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    if not LIVE:   # live tests must see the real keys
        monkeypatch.setenv("PRODUCTION_AGENTS_ANTHROPIC_API_KEY", "sk-test-anthropic")
        monkeypatch.setenv("VOYAGE_API_KEY", "pa-test-voyage")
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path / "agent-data"))
    # The opsec guard forbids identity writes under the obsidian vault
    # (agent_reports_vault.parent), so keep agent-data OUTSIDE the vault's parent —
    # mirroring production (~/agent-data is not under ~/obsidian).
    monkeypatch.setenv("AGENT_REPORTS_VAULT", str(tmp_path / "obsidian" / "agent-reports"))
    import agent_runtime.config
    agent_runtime.config.reset_config()


def _make_png(path: Path) -> Path:
    """Write a tiny valid PNG so MultimodalInput's path/format validation passes.

    The store builds a real MultimodalInput(text=caption, image_path=asset_path)
    even when the embedder is mocked, and MultimodalInput validates that the file
    exists and has a supported image extension.
    """
    # 1x1 transparent PNG.
    png_bytes = bytes(
        [
            0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x00, 0x00, 0x00, 0x0D,
            0x49, 0x48, 0x44, 0x52, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
            0x08, 0x06, 0x00, 0x00, 0x00, 0x1F, 0x15, 0xC4, 0x89, 0x00, 0x00, 0x00,
            0x0D, 0x49, 0x44, 0x41, 0x54, 0x78, 0x9C, 0x62, 0x00, 0x01, 0x00, 0x00,
            0x05, 0x00, 0x01, 0x0D, 0x0A, 0x2D, 0xB4, 0x00, 0x00, 0x00, 0x00, 0x49,
            0x45, 0x4E, 0x44, 0xAE, 0x42, 0x60, 0x82,
        ]
    )
    path.write_bytes(png_bytes)
    return path


@pytest.fixture
def png_asset(tmp_path: Path) -> Path:
    return _make_png(tmp_path / "asset.png")


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def flux_graph() -> dict:
    import json
    return json.loads((FIXTURES_DIR / "flux_txt2img_api.json").read_text(encoding="utf-8"))


@pytest.fixture
def flux_graph_file() -> Path:
    return FIXTURES_DIR / "flux_txt2img_api.json"


@pytest.fixture
def flux_template(flux_graph: dict):
    """A WorkflowTemplate built from the Flux fixture via the real slot inference."""
    from visual_generation.models import WorkflowTemplate
    from visual_generation.slot_inference import infer_slots

    inferred = infer_slots(flux_graph)
    return WorkflowTemplate(
        name="flux-txt2img",
        descriptor="basic flux still",
        graph=flux_graph,
        slot_map=inferred.slot_map,
        required_models=inferred.required_models,
    )


# The real, verified-working WAN 2.2 exported API graphs (not test fixtures — the
# actual registration artifacts in packages/visual-generation/workflows/), used so
# slot-inference tests exercise the real MoE two-stage topology, not a stand-in.
WORKFLOWS_DIR = Path(__file__).parent.parent / "workflows"


@pytest.fixture
def wan_t2v_graph() -> dict:
    import json
    return json.loads((WORKFLOWS_DIR / "wan2.2-t2v-14B-lightx2v-api.json").read_text(encoding="utf-8"))


@pytest.fixture
def wan_i2v_graph() -> dict:
    import json
    return json.loads((WORKFLOWS_DIR / "wan2.2-i2v-14B-lightx2v-api.json").read_text(encoding="utf-8"))


@pytest.fixture
def wan_t2v_template(wan_t2v_graph: dict):
    from visual_generation.models import WorkflowTemplate
    from visual_generation.slot_inference import infer_slots

    inferred = infer_slots(wan_t2v_graph)
    return WorkflowTemplate(
        name="wan2.2-t2v",
        descriptor="WAN 2.2 text-to-video",
        graph=wan_t2v_graph,
        slot_map=inferred.slot_map,
        required_models=inferred.required_models,
    )


@pytest.fixture
def wan_i2v_template(wan_i2v_graph: dict):
    from visual_generation.models import WorkflowTemplate
    from visual_generation.slot_inference import infer_slots

    inferred = infer_slots(wan_i2v_graph)
    return WorkflowTemplate(
        name="wan2.2-i2v",
        descriptor="WAN 2.2 image-to-video",
        graph=wan_i2v_graph,
        slot_map=inferred.slot_map,
        required_models=inferred.required_models,
    )
