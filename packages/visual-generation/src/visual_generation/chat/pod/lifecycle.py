"""One function per lifecycle command. Each builds an argument list and hands it to the runner;
what the commands do stays in scripts/pod and scripts/comfyui-bootstrap.

SSH always uses the direct-TCP form (`root@IP -p PORT`): the ssh.runpod.io proxy has no scp.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from visual_generation.chat.pod.runner import CommandResult, env_file, scripts_dir
from visual_generation.chat.pod.session import LOCAL_PORT, PodInfo
from visual_generation.chat.state import ChatState
from visual_generation.constants import DEFAULT_GPU_RATE_USD_PER_HR

# Seconds. `up` covers three create attempts plus the 180 s health check inside scripts/pod.
T_STATUS, T_UP, T_DOWN = 30.0, 420.0, 60.0
T_SSH_INFO, T_SCP, T_BOOTSTRAP, T_CHECK, T_EXPORT = 30.0, 60.0, 900.0, 30.0, 600.0
TUNNEL_SETTLE_SEC = 2.0

REMOTE_BOOTSTRAP = "/root/comfyui-bootstrap"
REMOTE_OUTPUT = "/comfy-data/output"
REMOTE_LOG = "/comfy-data/logs/comfyui.log"
SSH_KEY_ENV = "POD_SSH_KEY"
NO_KEY_MARK = "RUNPOD_API_KEY is unset"
NO_MODELS_MARK = "models not found"
KNOWN_BAD_TEMPLATES = {"cnne9dp3rt"}

NO_KEY = (
    "pod_up refused: RUNPOD_API_KEY is not available to scripts/pod. The script does not read .env itself, "
    "so this tool runs it as `op run --env-file=.env -- scripts/pod up`. That needs the `op` CLI on PATH and a "
    "RUNPOD_API_KEY=op://... line in {env}. Missing: {missing}."
)
VOLUME_MISSING = (
    "The pod has no models/ tree at /workspace/runpod-slim/ComfyUI/models, so the Global Volume is missing "
    "or empty. Rebuilding the models is outside this runbook. The pod is still billing: run pod_down."
)


# ── scripts/pod ──────────────────────────────────────────────────────────────


def parse_status(text: str) -> list[PodInfo]:
    """Read the `key: value` blocks `scripts/pod status` prints, one pod per block."""
    pods: list[PodInfo] = []
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if not sep or " " in key:
            continue
        if key == "id":
            pods.append(PodInfo(pod_id=value))
        elif pods and key == "name":
            pods[-1].name = value
        elif pods and key == "desiredStatus":
            pods[-1].status = value
        elif pods and key == "gpuCount":
            pods[-1].gpu_count = int(value) if value.isdigit() else 0
        elif pods and key == "costPerHr":
            try:
                pods[-1].cost_per_hr = float(value)
            except ValueError:
                pods[-1].cost_per_hr = None
    return pods


async def status(state: ChatState) -> tuple[list[PodInfo], CommandResult]:
    r = await state.runner().run([str(scripts_dir() / "pod"), "status"], timeout=T_STATUS, label="pod status")
    return (parse_status(r.stdout) if r.ok else []), r


def up_argv() -> list[str]:
    return ["op", "run", f"--env-file={env_file()}", "--", str(scripts_dir() / "pod"), "up"]


async def up(state: ChatState) -> CommandResult:
    return await state.runner().run(up_argv(), timeout=T_UP, label="pod up")


async def down(state: ChatState) -> CommandResult:
    return await state.runner().run([str(scripts_dir() / "pod"), "down"], timeout=T_DOWN, label="pod down")


def env_names(path: Path | None = None) -> dict[str, str | None] | None:
    """The variable names in `.env`, or None if there is no file. Values are never returned,
    except the two non-secret literals the template guard needs (TEMPLATE_ID, IMAGE)."""
    path = path or env_file()
    if not path.is_file():
        return None
    names: dict[str, str | None] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip().removeprefix("export ").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        names[name] = value.strip().strip("\"'") if name in ("TEMPLATE_ID", "IMAGE") else None
    return names


def api_key_problem() -> str | None:
    """Why `pod up` could not get its API key, as the refusal text; None when it can."""
    names = env_names()
    missing = []
    if shutil.which("op") is None:
        missing.append("op CLI")
    if names is None:
        missing.append(".env file")
    elif "RUNPOD_API_KEY" not in names:
        missing.append("RUNPOD_API_KEY line")
    return NO_KEY.format(env=env_file(), missing=", ".join(missing)) if missing else None


def env_problems(names: dict[str, str | None] | None) -> list[str]:
    """Runbook step 2: what in `.env` would make `pod up` fail or crash-loop."""
    if names is None:
        return [f"no .env at {env_file()}"]
    problems = [f"{k} is not set in .env" for k in ("RUNPOD_API_KEY", "IMAGE_NETWORK_VOLUME_ID") if k not in names]
    template = names.get("TEMPLATE_ID")
    if template in KNOWN_BAD_TEMPLATES:
        problems.append(f"TEMPLATE_ID={template} is the crash-looping ComfyUI template; use runpod-torch-v280")
    if "TEMPLATE_ID" in names and not template and "runpod/comfyui" in (names.get("IMAGE") or "").lower():
        problems.append("TEMPLATE_ID is empty and IMAGE is runpod/comfyui, which crash-loops on the Global Volume")
    return problems


# ── tracking: the session's view and the ledger's open entry ─────────────────


async def stop_tunnel(state: ChatState) -> None:
    proc = state.pod.tunnel
    if proc is not None and proc.returncode is None:
        proc.terminate()
        try:
            await proc.wait()
        except ProcessLookupError:
            pass
    state.pod.tunnel = None
    state.pod.endpoint = None


async def track(state: ChatState, pods: list[PodInfo], *, created_now: bool = False) -> PodInfo | None:
    """Make the session and the GPU ledger agree with what `status` just reported.

    A running pod with no open ledger entry gets one (marked `start_observed=False` unless this
    call created it); an open entry whose pod is gone is closed as `end_observed=False`."""
    ledger = state.ledger()
    live = next((p for p in pods if p.running), None)
    entry = ledger.open_pod_entry()
    if entry is not None and (live is None or entry["pod_id"] != live.pod_id):
        ledger.close_pod_uptime(entry["pod_id"], end_observed=False)
        entry = None
    if live is None:
        if state.pod.up:
            await stop_tunnel(state)
            state.pod.forget()
        return None
    if entry is None:
        rate = live.cost_per_hr if live.cost_per_hr is not None else DEFAULT_GPU_RATE_USD_PER_HR
        entry = ledger.open_pod_uptime(
            live.pod_id, rate, session_id=state.session_id, start_observed=created_now)
    if state.pod.pod_id != live.pod_id:
        await stop_tunnel(state)
        state.pod.forget()
    state.pod.info = live
    state.pod.started_at = entry["started_at"]
    state.pod.start_observed = bool(entry.get("start_observed", True))
    return live


async def close_tracking(state: ChatState) -> dict | None:  # type: ignore[type-arg]
    """The pod was deleted by this chat: close its ledger entry, charge the uptime, forget it."""
    pod_id = state.pod.pod_id
    await stop_tunnel(state)
    closed = state.ledger().close_pod_uptime(pod_id) if pod_id else None
    budget = state.gpu_budget()
    if closed and budget is not None:
        budget.charge(float(closed.get("cost_usd") or 0.0))
    state.pod.forget()
    return closed


# ── ssh (direct TCP) ─────────────────────────────────────────────────────────


def ssh_key() -> str:
    return os.environ.get(SSH_KEY_ENV) or str(Path.home() / ".ssh" / "id_ed25519")


def _options(state: ChatState) -> list[str]:
    # A known_hosts file of the session's own: RunPod reuses IP:port pairs across pods with new
    # host keys, which the user's ~/.ssh/known_hosts would reject as a changed host.
    hosts = state.pod.known_hosts or state.run_dir() / f"known_hosts-{state.pod.pod_id or 'pod'}"
    state.pod.known_hosts = hosts
    hosts.parent.mkdir(parents=True, exist_ok=True)
    return [
        "-i", ssh_key(), "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
        "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3",
        "-o", "StrictHostKeyChecking=accept-new", "-o", f"UserKnownHostsFile={hosts}",
    ]


def _target(state: ChatState) -> tuple[str, str]:
    return f"root@{state.pod.ssh_ip or '<IP>'}", str(state.pod.ssh_port or "<PORT>")


def ssh_argv(state: ChatState, *remote: str) -> list[str]:
    host, port = _target(state)
    return ["ssh", *_options(state), "-p", port, host, *remote]


def scp_up_argv(state: ChatState, local: Path, remote: str) -> list[str]:
    host, port = _target(state)
    return ["scp", *_options(state), "-P", port, str(local), f"{host}:{remote}"]


def scp_down_argv(state: ChatState, remote: str, local: Path) -> list[str]:
    host, port = _target(state)
    return ["scp", "-r", *_options(state), "-P", port, f"{host}:{remote}", str(local)]


def tunnel_argv(state: ChatState) -> list[str]:
    host, port = _target(state)
    return ["ssh", "-N", "-L", f"{LOCAL_PORT}:127.0.0.1:8188", *_options(state),
            "-o", "ExitOnForwardFailure=yes", "-p", port, host]


async def read_ssh_info(state: ChatState) -> tuple[bool, str]:
    """Runbook step 5: `runpodctl pod get <id> -o json`, keeping the direct-TCP ip and port."""
    assert state.pod.pod_id
    r = await state.runner().run(
        ["runpodctl", "pod", "get", state.pod.pod_id, "-o", "json"], timeout=T_SSH_INFO, label="pod ssh info")
    if not r.ok:
        return False, f"runpodctl pod get failed (rc {r.rc}): {r.last_line()}"
    try:
        ssh = (json.loads(r.stdout) or {}).get("ssh") or {}
    except json.JSONDecodeError:
        return False, "runpodctl pod get did not return JSON"
    ip, port = ssh.get("ip"), ssh.get("port")
    if not ip or not port:
        return False, f"the pod has no SSH endpoint yet ({ssh.get('error') or 'ip/port empty'}); try again shortly"
    state.pod.ssh_ip, state.pod.ssh_port = str(ip), int(port)
    return True, f"{ip}:{port}"


async def scp_bootstrap(state: ChatState) -> CommandResult:
    argv = scp_up_argv(state, scripts_dir() / "comfyui-bootstrap", REMOTE_BOOTSTRAP)
    return await state.runner().run(argv, timeout=T_SCP, label="scp comfyui-bootstrap")


async def run_bootstrap(state: ChatState) -> CommandResult:
    argv = ssh_argv(state, "bash", REMOTE_BOOTSTRAP)
    return await state.runner().run(argv, timeout=T_BOOTSTRAP, label="comfyui-bootstrap")


async def remote_stats(state: ChatState) -> CommandResult:
    """`/system_stats` asked from inside the pod: is ComfyUI itself up, tunnel aside?"""
    argv = ssh_argv(state, "curl", "-s", "--max-time", "10", "127.0.0.1:8188/system_stats")
    return await state.runner().run(argv, timeout=T_CHECK, label="system_stats on the pod")


async def open_tunnel(state: ChatState) -> None:
    await stop_tunnel(state)
    state.pod.tunnel = await state.runner().spawn(
        tunnel_argv(state), log_path=state.run_dir() / "tunnel.log", label="ssh tunnel")
    state.pod.endpoint = f"http://127.0.0.1:{LOCAL_PORT}"


async def copy_from_pod(state: ChatState, remote: str, local: Path) -> CommandResult:
    return await state.runner().run(scp_down_argv(state, remote, local), timeout=T_EXPORT, label=f"export {remote}")


async def keepalive_config(state: ChatState) -> tuple[bool, str]:
    """Runbook step 4: what ssh would actually use for this host (`ssh -G`)."""
    host, port = _target(state)
    r = await state.runner().run(["ssh", "-G", "-p", port, host], timeout=T_CHECK, label="ssh -G")
    found = dict(ln.split(None, 1) for ln in r.stdout.splitlines() if " " in ln)
    interval, count = found.get("serveraliveinterval", "0"), found.get("serveralivecountmax", "")
    ok = interval.isdigit() and 0 < int(interval) <= 30 and count == "3"
    return ok, f"ServerAliveInterval {interval}, ServerAliveCountMax {count or 'unset'}"


def can_watch() -> bool:
    return sys.platform == "darwin"       # `pod watch` asks through a macOS dialog


async def start_watch(state: ChatState) -> Path:
    log = state.run_dir() / "pod-watch.log"
    await state.runner().spawn([str(scripts_dir() / "pod"), "watch"], log_path=log, label="pod watch")
    return log


def stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
