"""Pod tools against the fake scripts directory: what is run, how it is run, and that each
checkpoint fails on its own. No pod is created and no key is read."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import visual_generation.chat.pod.lifecycle as lc
import visual_generation.chat.pod.runner as runner_mod
from visual_generation.chat.tools import tool_pack
from visual_generation.chat.tools.pod import UpArgs
from visual_generation.model_registry import ModelRegistry
from visual_generation.models import ModelAsset

from .conftest import Built  # type: ignore[import-not-found]
from .podkit import Comfy, attach  # type: ignore[import-not-found]

pytestmark = pytest.mark.asyncio

NINE = [f"char{i}-zimage-coraline-turbo.safetensors" for i in range(9)]
WAN = ["wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors"]


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lc, "TUNNEL_SETTLE_SEC", 0.01)


def tools(b: Built) -> dict[str, Any]:
    return {t.name: t for t in tool_pack(b.state)}


async def call(t: dict[str, Any], name: str, **kw: Any) -> Any:
    return await t[name].handler(t[name].input_model(**kw))


async def up(b: Built, tmp_path: Path, comfy: Comfy | None = None) -> dict[str, Any]:
    attach(b.state, tmp_path, comfy=comfy or Comfy())
    t = tools(b)
    r = await call(t, "pod_up")
    assert not r.is_error, r.text
    return t


# ── pod_status / pod_up ──────────────────────────────────────────────────────


async def test_status_with_no_pod_says_nothing_is_billing(build: Callable[..., Built], tmp_path: Path) -> None:
    b = build()
    attach(b.state, tmp_path)
    r = await call(tools(b), "pod_status")
    assert "No pod exists" in r.text and not b.state.pod.up


async def test_pod_up_runs_under_op_run_with_no_template_or_image_override(
    build: Callable[..., Built], tmp_path: Path, fake_scripts: Any
) -> None:
    b = build()
    audit, _ = attach(b.state, tmp_path)
    r = await call(tools(b), "pod_up")

    assert not r.is_error and "Created pod pod-abc ($0.60/hr)" in r.text
    (op_line,) = fake_scripts.ran("op ")
    assert op_line.startswith(f"op run --env-file={fake_scripts.env} -- {fake_scripts.dir / 'pod'} up")
    # the script saw the key only through op run, and no template or image override from the tool
    assert fake_scripts.ran("pod up")[0].endswith("TEMPLATE_ID=<unset> IMAGE=<unset> KEY=set")
    assert set(UpArgs.model_fields) == {"planned_minutes"}
    assert "env" not in inspect.signature(runner_mod.CommandRunner.run).parameters

    # billing started: its own ledger entry, open, at the pod's real rate
    entry = b.state.ledger().open_pod_entry()
    assert entry["type"] == "pod_uptime" and entry["pod_id"] == "pod-abc" and entry["rate_usd_per_hr"] == 0.6
    assert entry["start_observed"] is True and b.state.pod.up

    # explicit argv and the captured output are in the audit log
    rec = next(x for x in audit.read() if x.get("label") == "pod up")
    assert rec["kind"] == "subprocess" and rec["argv"][:3] == ["op", "run", f"--env-file={fake_scripts.env}"]
    assert rec["rc"] == 0 and "RUNNING with 1 GPU" in rec["stderr"]


async def test_the_pod_up_confirm_panel_text(build: Callable[..., Built], tmp_path: Path) -> None:
    b = build()
    attach(b.state, tmp_path)
    t = tools(b)
    assert t["pod_up"].preview_is_complete and await t["pod_up"].precheck(UpArgs()) is None
    assert await t["pod_up"].preview(UpArgs()) == "\n".join([
        "Create a RunPod pod. Billing starts when it is created and runs until pod_down.",
        "",
        "  Command:    op run --env-file=.env -- scripts/pod up",
        "  Pod name:   visual-generation",
        "  Existing:   none running (checked just now)",
        "  Rate:       unknown until created (scripts/pod documents about $2.09/hr).",
        "  Planned:    30 min, about $1.05",
        "  GPU so far: $0.00 this session of a $5.00 budget",
        "",
        "After this, ComfyUI is still not running. Next, each its own step:",
        "  pod_bootstrap, pod_tunnel, model_sync.",
        "The first render loads models for about 8 min (Z-Image). That time is billed.",
        "Template and image come from .env. This tool cannot change them.",
        "Uptime is written to the GPU ledger from create until pod_down.",
        "Idle check-in every 30 min while the pod is up.",
    ])
    b.state.ledger().open_pod_uptime("old", 0.69, started_at="2026-10-07T17:00:00+00:00")
    b.state.ledger().close_pod_uptime("old", ended_at="2026-10-07T17:30:00+00:00")
    text = await t["pod_up"].preview(UpArgs())
    assert "  Rate:       $0.69/hr (last pod, 2026-10-07). The real rate is read after create." in text
    assert "  Planned:    30 min, about $0.35" in text and t["pod_up"].estimate_cost(UpArgs()) == pytest.approx(0.345)


async def test_the_panel_says_when_a_running_pod_will_be_reused(
    build: Callable[..., Built], tmp_path: Path, fake_scripts: Any
) -> None:
    b = build()
    attach(b.state, tmp_path)
    fake_scripts.pod_exists()
    t = tools(b)
    text = await t["pod_up"].preview(UpArgs())
    assert "Existing:   pod pod-abc RUNNING, 1 GPU, $0.60/hr. scripts/pod will reuse it; no new pod is created." in text
    r = await call(t, "pod_up")
    assert "Reusing pod pod-abc" in r.text
    assert b.state.ledger().open_pod_entry()["start_observed"] is False     # it was up before we saw it


async def test_a_missing_api_key_is_explained_not_dumped(
    build: Callable[..., Built], tmp_path: Path, fake_scripts: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = build()
    attach(b.state, tmp_path)
    t = tools(b)
    monkeypatch.setenv("FAKE_POD_UP", "no_key")
    r = await call(t, "pod_up")
    assert r.is_error and r.text.startswith("pod_up refused: RUNPOD_API_KEY is not available to scripts/pod.")
    assert "op run --env-file=.env -- scripts/pod up" in r.text and not b.state.pod.up
    assert b.state.ledger().open_pod_entry() is None

    fake_scripts.env.write_text("TEMPLATE_ID=runpod-torch-v280\n")
    refusal = await t["pod_up"].precheck(UpArgs())          # refused before the director is asked
    assert refusal and "Missing: RUNPOD_API_KEY line." in refusal
    fake_scripts.env.unlink()
    assert "Missing: .env file." in (await t["pod_up"].precheck(UpArgs()))


async def test_a_hung_script_is_killed_at_the_timeout(
    build: Callable[..., Built], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = build()
    audit, _ = attach(b.state, tmp_path)
    monkeypatch.setenv("FAKE_POD_UP", "hang")
    monkeypatch.setattr(lc, "T_UP", 0.3)
    r = await call(tools(b), "pod_up")
    assert r.is_error and "timed out" in r.text
    assert next(x for x in audit.read() if x.get("label") == "pod up")["timed_out"] is True


# ── three checkpoints, three separate failures ───────────────────────────────


async def test_ssh_uses_the_direct_tcp_form_never_the_proxy(
    build: Callable[..., Built], tmp_path: Path, fake_scripts: Any
) -> None:
    b = build()
    t = await up(b, tmp_path)
    assert not (await call(t, "pod_bootstrap")).is_error
    assert not (await call(t, "pod_tunnel")).is_error
    await asyncio.sleep(0.3)                    # let the spawned tunnel write its log line
    scp, = fake_scripts.ran("scp ")
    assert "-P 22017" in scp and scp.endswith(f"{fake_scripts.dir / 'comfyui-bootstrap'} root@203.0.113.7:/root/comfyui-bootstrap")
    ssh = fake_scripts.ran("ssh ")
    assert any(ln.endswith("-p 22017 root@203.0.113.7 bash /root/comfyui-bootstrap") for ln in ssh)
    assert any("-N -L 8188:127.0.0.1:8188" in ln and "ExitOnForwardFailure=yes" in ln for ln in ssh)
    assert all("ServerAliveInterval=30" in ln and "BatchMode=yes" in ln for ln in ssh)
    assert "ssh.runpod.io" not in "\n".join(fake_scripts.log())
    assert b.state.pod.endpoint == "http://127.0.0.1:8188" and b.state.pod.tunnel_alive
    await lc.stop_tunnel(b.state)


async def test_bootstrap_tunnel_and_sync_fail_independently(
    build: Callable[..., Built], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = build()
    comfy = Comfy()
    t = await up(b, tmp_path, comfy)
    pod = b.state.pod

    monkeypatch.setenv("FAKE_BOOTSTRAP", "fail")
    r = await call(t, "pod_bootstrap")
    assert r.is_error and "running the bootstrap script (the copy succeeded)" in r.text and not pod.bootstrapped
    monkeypatch.setenv("FAKE_BOOTSTRAP", "ok")
    assert not (await call(t, "pod_bootstrap")).is_error and pod.bootstrapped

    monkeypatch.setenv("FAKE_TUNNEL", "dies")
    monkeypatch.setattr(lc, "TUNNEL_SETTLE_SEC", 0.5)     # long enough for the fake ssh to exit
    r = await call(t, "pod_tunnel")
    assert r.is_error and "ComfyUI answers on the pod, but the tunnel did not come up" in r.text
    assert "rc 255" in r.text and pod.bootstrapped and pod.endpoint is None       # bootstrap still stands
    monkeypatch.setenv("FAKE_REMOTE", "down")
    r = await call(t, "pod_tunnel")
    assert r.is_error and "does not answer /system_stats on the pod itself" in r.text
    monkeypatch.setenv("FAKE_TUNNEL", "ok")
    monkeypatch.setenv("FAKE_REMOTE", "ok")
    monkeypatch.setattr(lc, "TUNNEL_SETTLE_SEC", 0.01)
    assert not (await call(t, "pod_tunnel")).is_error and pod.tunnel_alive

    comfy.down = True
    refusal = await t["model_sync"].precheck(t["model_sync"].input_model())
    assert refusal and refusal.startswith("Platform-layer finding") and "the tunnel is open but ComfyUI does not answer" in refusal
    assert pod.tunnel_alive and pod.bootstrapped and not pod.synced              # the other two still stand
    await lc.stop_tunnel(b.state)


async def test_a_pod_with_no_models_reports_the_missing_volume(
    build: Callable[..., Built], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = build()
    t = await up(b, tmp_path)
    monkeypatch.setenv("FAKE_BOOTSTRAP", "no_models")
    r = await call(t, "pod_bootstrap")
    assert r.is_error and "the Global Volume is missing or empty" in r.text and "still billing" in r.text
    assert r.data["volume_missing"] is True


async def test_an_ssh_endpoint_that_is_not_ready_is_its_own_message(
    build: Callable[..., Built], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_scripts: Any
) -> None:
    b = build()
    t = await up(b, tmp_path)
    monkeypatch.setenv("FAKE_SSH_INFO", "not_ready")
    r = await call(t, "pod_bootstrap")
    assert r.is_error and "SSH connection info" in r.text and "pod not ready" in r.text
    assert fake_scripts.ran("scp ") == []


# ── model_sync: show what is dropped before writing ──────────────────────────


async def test_model_sync_shows_the_dropped_list_before_it_writes(build: Callable[..., Built], tmp_path: Path) -> None:
    b = build()
    comfy = Comfy(loras=WAN)
    t = await up(b, tmp_path, comfy)
    await call(t, "pod_bootstrap")
    await call(t, "pod_tunnel")
    reg = ModelRegistry(b.state.data_dir / "models.json")
    reg.replace([*[ModelAsset(name=n, kind="lora", source="synced") for n in NINE],
                 ModelAsset(name="narrator.safetensors", kind="lora", source="registered", identity_bearing=True)])
    sync = t["model_sync"]
    a = sync.input_model()

    assert sync.effect.value == "memory_write" and await sync.precheck(a) is None
    panel = await sync.preview(a)
    assert "DROPPED (9)" in panel and all(f"- {n}  [lora]" in panel for n in NINE)
    assert "These entries leave the registry." in panel
    assert "- narrator.safetensors  [lora]  [identity-bearing]" in panel and "Kept (1)" in panel
    assert len(reg.list_models()) == 10                       # nothing written by showing it

    r = await sync.handler(a)
    names = {m.name for m in reg.list_models()}
    assert not r.is_error and r.data["dropped"] == NINE and not names & set(NINE)
    assert "narrator.safetensors" in names and WAN[0] in names and b.state.pod.synced

    again = await sync.precheck(a)                            # once per new pod
    assert again and "already synced against this pod" in again and "force=true" in again
    assert await sync.precheck(sync.input_model(force=True)) is None
    await lc.stop_tunnel(b.state)


# ── export, then delete ──────────────────────────────────────────────────────


async def test_export_then_down_records_uptime_as_its_own_ledger_entry(
    build: Callable[..., Built], tmp_path: Path, fake_scripts: Any
) -> None:
    b = build()
    t = await up(b, tmp_path)
    await call(t, "pod_bootstrap")
    pod = b.state.pod
    pod.unexported = 2
    assert "2 render(s) since the last export" in await t["pod_down"].preview(t["pod_down"].input_model())

    r = await call(t, "export_artifacts")
    dest = Path(r.data["export_dir"])
    assert not r.is_error and (dest / "output" / "ComfyUI_00001_.png").is_file() and pod.unexported == 0
    assert "identity/pod-exports/pod-abc-" in str(dest)            # under the secured root
    assert json.loads((dest / "export-manifest.json").read_text())["pod_id"] == "pod-abc"
    assert any("-r" in ln and "root@203.0.113.7:/comfy-data/output" in ln for ln in fake_scripts.ran("scp "))

    b.state.ledger().record_session(0.10)                           # an inference estimate, kept apart
    r = await call(t, "pod_down")
    ledger = b.state.ledger()
    assert not r.is_error and "pod_status confirms none remain" in r.text and "written to the GPU ledger" in r.text
    (entry,) = ledger.entries("pod_uptime")
    assert entry["ended_at"] and entry["end_observed"] is True and ledger.open_pod_entry() is None
    assert ledger.cumulative() == pytest.approx(0.10) and not pod.up
    assert b.state.session.budgets.gpu.spent == pytest.approx(entry["cost_usd"])
    assert fake_scripts.ran("pod down") and fake_scripts.ran("pod status")


async def test_export_reports_an_output_whose_record_is_incomplete(build: Callable[..., Built], tmp_path: Path) -> None:
    b = build()
    t = await up(b, tmp_path)
    orphan = tmp_path / "assets" / "abc.png"
    orphan.parent.mkdir()
    orphan.write_bytes(b"png")
    b.state.pod.output_paths.append(str(orphan))
    b.state.pod.unexported = 1
    r = await call(t, "export_artifacts")
    assert r.is_error and "abc.png: missing abc.graph.json, abc.provenance.json" in r.text
    assert b.state.pod.unexported == 1                              # not counted as exported


# ── dry-run ──────────────────────────────────────────────────────────────────


async def test_dry_run_runs_no_ssh_for_the_tools_the_gate_does_not_confirm(
    build: Callable[..., Built], tmp_path: Path, fake_scripts: Any
) -> None:
    b = build()
    attach(b.state, tmp_path, dry_run=True)
    t = tools(b)
    for name in ("pod_bootstrap", "pod_tunnel", "export_artifacts"):
        r = await call(t, name)
        assert not r.is_error and r.text.startswith("[dry-run] would run:") and r.data["dry_run"]
        assert "root@<IP>" in r.text
    assert "ssh.runpod.io" not in r.text
    assert fake_scripts.ran("ssh ") == [] and fake_scripts.ran("scp ") == [] and fake_scripts.ran("runpodctl") == []
    assert "nothing fetched" in await t["model_sync"].preview(t["model_sync"].input_model())
