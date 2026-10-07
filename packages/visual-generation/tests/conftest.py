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


@pytest.fixture
def zimage_lora_template():
    """The real Z-Image-Turbo LoRA workflow, with its LoRA loader baked to 'narrator-zimage'."""
    import json

    from visual_generation.models import WorkflowTemplate
    from visual_generation.slot_inference import infer_slots

    graph = json.loads((WORKFLOWS_DIR / "z-image-turbo-lora-api.json").read_text(encoding="utf-8"))
    inferred = infer_slots(graph)
    return WorkflowTemplate(
        name="z-image-turbo-lora", descriptor="z-image stills with a LoRA loader", graph=graph,
        slot_map=inferred.slot_map, required_models=inferred.required_models,
    )


# ── a fake scripts directory: no test can reach scripts/pod, runpodctl, ssh or op ──

_FAKE_POD = r"""#!/usr/bin/env bash
echo "pod $* | TEMPLATE_ID=${TEMPLATE_ID-<unset>} IMAGE=${IMAGE-<unset>} KEY=${RUNPOD_API_KEY:+set}" >> "$FAKE_LOG"
state="$FAKE_STATE/pod"
case "$1" in
  up)
    if [[ "${FAKE_POD_UP:-ok}" == "no_key" ]]; then echo "error: RUNPOD_API_KEY is unset. Pod creation now goes..." >&2; exit 1; fi
    if [[ "${FAKE_POD_UP:-ok}" == "capacity" ]]; then echo "!!! ERROR: could not create a pod with a GPU after 3 attempt(s)" >&2; exit 1; fi
    if [[ "${FAKE_POD_UP:-ok}" == "hang" ]]; then sleep 30; fi
    if [[ -f "$state" ]]; then echo "reusing pod pod-abc (RUNNING with 1 GPU(s))." >&2; exit 0; fi
    touch "$state"; echo "pod pod-abc RUNNING with 1 GPU(s)." >&2 ;;
  down) rm -f "$state"; echo "deleted pod pod-abc." >&2 ;;
  status)
    if [[ "${FAKE_POD_STATUS:-ok}" == "fail" ]]; then echo "error: runpodctl not found on PATH." >&2; exit 1; fi
    if [[ -f "$state" ]]; then printf 'id:            pod-abc\nname:          visual-generation\ndesiredStatus: RUNNING\ngpuCount:      1\ncostPerHr:     0.6\n\n'; fi ;;
  watch) sleep 30 ;;
esac
"""
_FAKE_OP = r"""#!/usr/bin/env bash
echo "op $*" >> "$FAKE_LOG"
while [[ $# -gt 0 && "$1" != "--" ]]; do shift; done
shift
RUNPOD_API_KEY=resolved-secret exec "$@"
"""
_FAKE_RUNPODCTL = r"""#!/usr/bin/env bash
echo "runpodctl $*" >> "$FAKE_LOG"
if [[ "${FAKE_SSH_INFO:-ok}" == "not_ready" ]]; then echo '{"id":"pod-abc","ssh":{"error":"pod not ready"}}'; exit 0; fi
echo '{"id":"pod-abc","ssh":{"ip":"203.0.113.7","port":22017}}'
"""
_FAKE_SSH = r"""#!/usr/bin/env bash
echo "ssh $*" >> "$FAKE_LOG"
all=" $* "
if [[ "$all" == *" -G "* ]]; then printf 'serveraliveinterval %s\nserveralivecountmax 3\n' "${FAKE_KEEPALIVE:-30}"; exit 0; fi
if [[ "$all" == *" -N "* ]]; then
  if [[ "${FAKE_TUNNEL:-ok}" == "dies" ]]; then echo "bind: Address already in use" >&2; exit 255; fi
  sleep 30; exit 0
fi
if [[ "$all" == *" curl "* ]]; then
  if [[ "${FAKE_REMOTE:-ok}" == "down" ]]; then echo "curl: (7) Failed to connect" >&2; exit 7; fi
  echo '{"system": {"os": "posix"}}'; exit 0
fi
if [[ "$all" == *" bash "* ]]; then
  if [[ "${FAKE_BOOTSTRAP:-ok}" == "no_models" ]]; then echo "error: /workspace/runpod-slim/ComfyUI/models not found. Expected the volume's pre-populated model" >&2; exit 1; fi
  if [[ "${FAKE_BOOTSTRAP:-ok}" == "fail" ]]; then echo "error: ComfyUI process exited immediately" >&2; exit 1; fi
  echo "ComfyUI started (pid 4242), models dir: volume."; exit 0
fi
"""
_FAKE_SCP = r"""#!/usr/bin/env bash
echo "scp $*" >> "$FAKE_LOG"
if [[ "${FAKE_SCP:-ok}" == "fail" ]]; then echo "scp: Connection closed" >&2; exit 1; fi
dest="${@: -1}"
if [[ " $* " == *" -r "* ]]; then mkdir -p "$dest/output"; echo png > "$dest/output/ComfyUI_00001_.png"; fi
"""


class FakeScripts:
    """The fake scripts directory plus what was run through it."""

    def __init__(self, root: Path) -> None:
        self.dir = root / "scripts"
        self.env = root / ".env"
        self.log_path = root / "fake.log"
        self.state = root / "state"

    def log(self) -> list[str]:
        return self.log_path.read_text().splitlines() if self.log_path.exists() else []

    def ran(self, prefix: str) -> list[str]:
        return [ln for ln in self.log() if ln.startswith(prefix)]

    def pod_exists(self, yes: bool = True) -> None:
        (self.state / "pod").touch() if yes else (self.state / "pod").unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def fake_scripts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeScripts:
    fake = FakeScripts(tmp_path / "fake-repo")
    fake.dir.mkdir(parents=True)
    fake.state.mkdir()
    for name, body in (("pod", _FAKE_POD), ("op", _FAKE_OP), ("runpodctl", _FAKE_RUNPODCTL),
                       ("ssh", _FAKE_SSH), ("scp", _FAKE_SCP), ("comfyui-bootstrap", "#!/usr/bin/env bash\n")):
        path = fake.dir / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)
    fake.env.write_text(
        "RUNPOD_API_KEY=op://Personal/runpod/credential\nIMAGE_NETWORK_VOLUME_ID=vol-123\n"
        "TEMPLATE_ID=runpod-torch-v280\n", encoding="utf-8")
    monkeypatch.setenv("VISUAL_GENERATION_SCRIPTS_DIR", str(fake.dir))
    monkeypatch.setenv("PATH", f"{fake.dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_LOG", str(fake.log_path))
    monkeypatch.setenv("FAKE_STATE", str(fake.state))
    for name in ("TEMPLATE_ID", "IMAGE", "RUNPOD_API_KEY", "POD_SSH_KEY"):
        monkeypatch.delenv(name, raising=False)
    return fake
