"""Pod tools: status, create, install, connect, sync, export, delete.

Each is one checkpoint and runs nothing else implicitly: on 2026-10-07 the bootstrap, the tunnel
and the model sync each failed on their own. The lifecycle itself stays in scripts/pod and
scripts/comfyui-bootstrap (see chat/pod/lifecycle.py for the exact commands).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_shell.tools.registry import EffectClass, ToolResult, ToolSpec
from pydantic import BaseModel, Field

from visual_generation.chat.pod import lifecycle as lc
from visual_generation.chat.pod.runner import CommandResult, show
from visual_generation.chat.state import ChatState
from visual_generation.chat.tools._common import fail, ok
from visual_generation.chat.tools.generation import endpoint_problem, record_finding, resolve_endpoint
from visual_generation.comfyui_client import ComfyUIError
from visual_generation.constants import IDENTITY_SUBDIR
from visual_generation.model_registry import ModelRegistry
from visual_generation.model_sync import ReconcileResult, parse_object_info, reconcile

DOCUMENTED_RATE_USD_PER_HR = 2.09          # scripts/pod's own figure, used until a real rate is known
CHECKIN_MINUTES = 30
TUNNEL_TRIES = 5


class NoArgs(BaseModel):
    pass


class UpArgs(BaseModel):
    planned_minutes: int = Field(default=30, ge=1, le=720, description="How long you expect to keep the pod up.")


class SyncArgs(BaseModel):
    endpoint: str | None = Field(default=None, description="ComfyUI URL. Default: the tunnel pod_tunnel opened.")
    force: bool = Field(default=False, description="Sync again although this pod was already synced.")


NEED_POD = "No pod is tracked in this session. Run pod_status (a pod already up) or pod_up."


def _tail(r: CommandResult, n: int = 6) -> str:
    return "\n".join(r.output.splitlines()[-n:])


def _failed(what: str, r: CommandResult) -> str:
    return f"{what} failed (rc {r.rc}{', timed out' if r.timed_out else ''}):\n{_tail(r)}"


def _dry(*argvs: list[str]) -> ToolResult:
    return ok("[dry-run] would run:\n" + "\n".join("  " + show(a) for a in argvs), data={"dry_run": True})


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def verify_local(asset: Path) -> list[str]:
    """Problems with one output's local record: the image, the submitted graph and the provenance
    file must all exist, and the two hashes the provenance file states must match the files."""
    graph, prov = asset.parent / f"{asset.stem}.graph.json", asset.parent / f"{asset.stem}.provenance.json"
    missing = [p.name for p in (asset, graph, prov) if not p.is_file()]
    if missing:
        return [f"{asset.name}: missing {', '.join(missing)}"]
    record = json.loads(prov.read_text(encoding="utf-8"))
    problems = []
    stated = [o.get("sha256") for o in record.get("outputs", [])]
    if _sha256(asset) not in stated:
        problems.append(f"{asset.name}: image hash does not match its provenance record")
    if record.get("submitted_graph_sha256") != _sha256(graph):
        problems.append(f"{asset.name}: submitted-graph hash does not match its provenance record")
    return problems


def render_sync(endpoint: str, existing: list[Any], result: ReconcileResult) -> str:
    by_name = {a.name: a for a in existing}

    def row(name: str) -> str:
        a = by_name[name]
        return f"    - {name}  [{a.kind}]" + ("  [identity-bearing]" if a.identity_bearing else "")

    lines = [
        f"Rewrite the model registry to match the pod at {endpoint}.",
        f"  +{len(result.added)} new, ~{len(result.refreshed)} refreshed, {len(result.kept_absent)} kept "
        f"but absent, -{len(result.dropped)} dropped. {len(result.merged)} entries after the write.",
    ]
    if result.dropped:
        lines += ["", f"  DROPPED ({len(result.dropped)}): on the registry from an earlier sync, not on this pod's volume",
                  *[row(n) for n in result.dropped],
                  "  These entries leave the registry. Specs and canon that name them will be skipped or",
                  "  rejected until a pod that has them is synced."]
    if result.kept_absent:
        lines += ["", f"  Kept ({len(result.kept_absent)}): registered by hand, not on this pod; flagged absent",
                  *[row(n) for n in result.kept_absent]]
    if not result.dropped:
        lines += ["", "  Nothing is dropped."]
    return "\n".join(lines)


def make_pod_tools(state: ChatState) -> list[ToolSpec]:
    pod = state.pod

    def registry() -> ModelRegistry:
        return ModelRegistry(state.data_dir / "models.json")

    # pod_status --------------------------------------------------------------

    async def status_tool(a: NoArgs) -> ToolResult:
        pods, r = await lc.status(state)
        if not r.ok:
            return fail(_failed("scripts/pod status", r))
        live = await lc.track(state, pods)
        if not pods:
            return ok("No pod exists. Nothing is billing.", data={"pods": []})
        lines = [f"{p.pod_id}  {p.name}  {p.status}  gpu={p.gpu_count}  "
                 + (f"${p.cost_per_hr:.2f}/hr" if p.cost_per_hr is not None else "rate unknown") for p in pods]
        if live:
            lines.append(f"Tracking {pod.describe()}. ComfyUI installed this session: {'yes' if pod.bootstrapped else 'not yet'}; "
                         f"tunnel: {'open' if pod.tunnel_alive else 'not open'}; registry synced: {'yes' if pod.synced else 'no'}.")
        return ok("\n".join(lines), data={"pods": [p.pod_id for p in pods], "running": live.pod_id if live else None})

    # pod_up ------------------------------------------------------------------

    def last_rate() -> tuple[float, str]:
        rows = state.ledger().entries("pod_uptime")
        if rows:
            return float(rows[-1]["rate_usd_per_hr"]), f"last pod, {rows[-1]['started_at'][:10]}"
        return DOCUMENTED_RATE_USD_PER_HR, ""

    def up_estimate(a: UpArgs) -> float:
        return last_rate()[0] * a.planned_minutes / 60.0

    async def up_precheck(a: UpArgs) -> str | None:
        return lc.api_key_problem()

    async def up_preview(a: UpArgs) -> str:
        pods, r = await lc.status(state)
        live = next((p for p in pods if p.running), None)
        if not r.ok:
            existing = f"could not check ({r.last_line() or f'rc {r.rc}'})"
        elif live:
            live_rate = f"${live.cost_per_hr:.2f}/hr" if live.cost_per_hr is not None else "rate unknown"
            existing = (f"pod {live.pod_id} RUNNING, {live.gpu_count} GPU, {live_rate}. scripts/pod will reuse it; "
                        "no new pod is created.")
        else:
            existing = "none running (checked just now)"
        rate, source = last_rate()
        rate_line = (f"${rate:.2f}/hr ({source}). The real rate is read after create." if source
                     else f"unknown until created (scripts/pod documents about ${rate:.2f}/hr).")
        budget = state.gpu_budget()
        lines = [
            "Create a RunPod pod. Billing starts when it is created and runs until pod_down.",
            "",
            "  Command:    op run --env-file=.env -- scripts/pod up",
            "  Pod name:   visual-generation",
            f"  Existing:   {existing}",
            f"  Rate:       {rate_line}",
            f"  Planned:    {a.planned_minutes} min, about ${up_estimate(a) + 1e-9:.2f}",
        ]
        if budget is not None:
            cap = "no budget set" if budget.max_usd is None else f"a ${budget.max_usd:.2f} budget"
            lines.append(f"  GPU so far: ${budget.spent:.2f} this session of {cap}")
        lines += [
            "",
            "After this, ComfyUI is still not running. Next, each its own step:",
            "  pod_bootstrap, pod_tunnel, model_sync.",
            "The first render loads models for about 8 min (Z-Image). That time is billed.",
            "Template and image come from .env. This tool cannot change them.",
            "Uptime is written to the GPU ledger from create until pod_down.",
            f"Idle check-in every {CHECKIN_MINUTES} min while the pod is up.",
        ]
        return "\n".join(lines)

    async def up_tool(a: UpArgs) -> ToolResult:
        problem = lc.api_key_problem()
        if problem:
            return fail(problem)
        r = await lc.up(state)
        if not r.ok:
            if lc.NO_KEY_MARK in r.output:
                return fail(lc.NO_KEY.format(env=lc.env_file(), missing="RUNPOD_API_KEY line"))
            return fail(_failed("scripts/pod up", r) + "\nNo pod was left running by a failed create "
                        "(scripts/pod deletes it). Confirm with pod_status.")
        reused = "reusing pod" in r.output
        pods, s = await lc.status(state)
        live = await lc.track(state, pods, created_now=not reused) if s.ok else None
        if live is None:
            return fail("scripts/pod up reported success but pod_status shows no running pod:\n" + _tail(s))
        pod.last_checkin = time.monotonic()
        rate = f"${live.cost_per_hr:.2f}/hr" if live.cost_per_hr is not None else "rate unknown"
        verb = "Reusing" if reused else "Created"
        return ok(f"{verb} pod {live.pod_id} ({rate}). Billing is running and uptime is in the GPU ledger. "
                  "ComfyUI is not installed yet: run pod_bootstrap, then pod_tunnel, then model_sync.",
                  data={"pod_id": live.pod_id, "cost_per_hr": live.cost_per_hr, "reused": reused})

    # pod_bootstrap -----------------------------------------------------------

    async def bootstrap_tool(a: NoArgs) -> ToolResult:
        if state.dry_run:
            return _dry(["runpodctl", "pod", "get", pod.pod_id or "<pod-id>", "-o", "json"],
                        lc.scp_up_argv(state, lc.scripts_dir() / "comfyui-bootstrap", lc.REMOTE_BOOTSTRAP),
                        lc.ssh_argv(state, "bash", lc.REMOTE_BOOTSTRAP))
        if not pod.up:
            return fail(NEED_POD)
        found, detail = await lc.read_ssh_info(state)
        if not found:
            return fail(f"Checkpoint failed: SSH connection info. {detail}")
        r = await lc.scp_bootstrap(state)
        if not r.ok:
            return fail("Checkpoint failed: copying the bootstrap script. " + _failed("scp", r))
        state.notify("installing and starting ComfyUI on the pod (the venv is rebuilt on every new pod; a few minutes)")
        r = await lc.run_bootstrap(state)
        if not r.ok:
            if lc.NO_MODELS_MARK in r.output:
                return fail("Checkpoint failed: running the bootstrap script. " + lc.VOLUME_MISSING,
                            data={"volume_missing": True})
            return fail("Checkpoint failed: running the bootstrap script (the copy succeeded). "
                        + _failed("comfyui-bootstrap", r))
        pod.bootstrapped = True
        return ok(f"ComfyUI is installed and started on {pod.pod_id} ({detail}). {r.last_line()}\n"
                  "It listens on the pod only: run pod_tunnel next.", data={"pod_id": pod.pod_id, "ssh": detail})

    # pod_tunnel --------------------------------------------------------------

    async def tunnel_tool(a: NoArgs) -> ToolResult:
        if state.dry_run:
            return _dry(lc.tunnel_argv(state), lc.ssh_argv(state, "curl", "-s", "127.0.0.1:8188/system_stats"))
        if not pod.up:
            return fail(NEED_POD)
        if pod.ssh_ip is None:
            found, detail = await lc.read_ssh_info(state)
            if not found:
                return fail(f"Checkpoint failed: SSH connection info. {detail}")
        r = await lc.remote_stats(state)
        try:
            answered = r.ok and isinstance(json.loads(r.stdout), dict)
        except json.JSONDecodeError:
            answered = False
        if not answered:
            return fail("Checkpoint failed: ComfyUI does not answer /system_stats on the pod itself, so a tunnel "
                        "would lead nowhere. Run pod_bootstrap (it starts ComfyUI if it is not running).\n" + _tail(r))
        await lc.open_tunnel(state)
        endpoint = pod.endpoint
        assert endpoint is not None
        error = ""
        for _ in range(TUNNEL_TRIES):
            await asyncio.sleep(lc.TUNNEL_SETTLE_SEC)
            if not pod.tunnel_alive:
                break
            try:
                await state.comfy(endpoint).system_stats()
                if not pod.tunnel_alive:      # something else on the port answered; the tunnel is gone
                    break
                return ok(f"Tunnel open. ComfyUI answers on the pod and through the tunnel at {endpoint}. "
                          + ("" if pod.synced else "Run model_sync once for this pod before generating."),
                          data={"endpoint": endpoint})
            except ComfyUIError as exc:
                error = str(exc)
        rc = pod.tunnel.returncode if pod.tunnel is not None else None
        log = state.run_dir() / "tunnel.log"
        tail = "\n".join(log.read_text(errors="replace").splitlines()[-4:]) if log.is_file() else ""
        await lc.stop_tunnel(state)
        why = f"the ssh process exited (rc {rc})" if rc is not None else f"nothing answered through it ({error})"
        return fail("Checkpoint failed: ComfyUI answers on the pod, but the tunnel did not come up: "
                    f"{why}. Is local port 8188 already in use?\n{tail}")

    # model_sync --------------------------------------------------------------

    async def sync_plan(a: SyncArgs) -> dict[str, Any]:
        endpoint = resolve_endpoint(state, a.endpoint)
        assert endpoint is not None
        object_info = await state.comfy(endpoint).object_info()
        existing = registry().list_models()
        hit = {"key": a.model_dump_json(), "endpoint": endpoint, "existing": existing,
               "result": reconcile(existing, parse_object_info(object_info))}
        state.shown["model_sync"] = hit
        return hit

    async def sync_precheck(a: SyncArgs) -> str | None:
        state.shown.pop("model_sync", None)
        if state.dry_run:
            return None
        endpoint = resolve_endpoint(state, a.endpoint)
        problem = await endpoint_problem(state, endpoint)
        if problem:
            record_finding(state, "model_sync", problem)
            return problem.replace(" and no GPU time was spent by this call", "").replace("submitted", "written")
        if pod.synced and endpoint == pod.endpoint and not a.force:
            return (f"The registry was already synced against this pod ({pod.pod_id}) at {pod.synced_at}. "
                    "It runs once per new pod; pass force=true to sync again.")
        try:
            await sync_plan(a)
        except ComfyUIError as e:
            return f"Could not read /object_info: {e}"
        return None

    async def sync_preview(a: SyncArgs) -> str:
        if state.dry_run:
            return (f"Would fetch /object_info from {resolve_endpoint(state, a.endpoint) or 'the tunnel'}, show what the "
                    "registry would gain and DROP, and rewrite it after confirmation. (dry-run: nothing fetched)")
        hit = state.shown.get("model_sync") or await sync_plan(a)
        return render_sync(hit["endpoint"], hit["existing"], hit["result"])

    async def sync_tool(a: SyncArgs) -> ToolResult:
        hit = state.shown.pop("model_sync", None)
        if hit is None or hit["key"] != a.model_dump_json():
            try:
                hit = await sync_plan(a)
            except (ComfyUIError, AssertionError) as e:
                return fail(f"Could not read /object_info: {e}")
            state.shown.pop("model_sync", None)
        result: ReconcileResult = hit["result"]
        reg = registry()
        reg.replace(result.merged)
        if pod.up and hit["endpoint"] == pod.endpoint:
            pod.synced_pod_id = pod.pod_id
            pod.synced_at = datetime.now(UTC).strftime("%H:%M UTC")
        return ok(f"Registry written: {len(result.merged)} asset(s) at {reg.path}. +{len(result.added)} new, "
                  f"-{len(result.dropped)} dropped" + (f" ({', '.join(result.dropped)})" if result.dropped else "") + ".",
                  data={"added": result.added, "dropped": result.dropped, "kept_absent": result.kept_absent,
                        "total": len(result.merged)})

    # export_artifacts --------------------------------------------------------

    def export_dir() -> Path:
        # Under the secured root: raw pod output can hold identity-bearing images.
        return state.data_dir / IDENTITY_SUBDIR / "pod-exports" / f"{pod.pod_id or 'pod'}-{lc.stamp()}"

    async def export_tool(a: NoArgs) -> ToolResult:
        if state.dry_run:
            dest = export_dir()
            return _dry(lc.scp_down_argv(state, lc.REMOTE_OUTPUT, dest), lc.scp_down_argv(state, lc.REMOTE_LOG, dest))
        if not pod.up:
            return fail(NEED_POD)
        if pod.ssh_ip is None:
            found, detail = await lc.read_ssh_info(state)
            if not found:
                return fail(f"Checkpoint failed: SSH connection info. {detail}")
        problems = [p for path in pod.output_paths for p in verify_local(Path(path))]
        dest = export_dir()
        dest.mkdir(parents=True, exist_ok=True)
        out = await lc.copy_from_pod(state, lc.REMOTE_OUTPUT, dest)
        log = await lc.copy_from_pod(state, lc.REMOTE_LOG, dest)
        copied = sorted(str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file())
        manifest = {
            "pod_id": pod.pod_id, "exported_at": datetime.now(UTC).isoformat(), "session_id": state.session_id,
            "generation_ids": pod.generation_ids, "local_outputs": pod.output_paths, "local_problems": problems,
            "copied": copied, "output_copy_ok": out.ok, "log_copy_ok": log.ok,
        }
        (dest / "export-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        lines = [f"Local records: {len(pod.output_paths)} output(s) rendered this session, "
                 + ("each with its image, submitted graph and provenance file; hashes match."
                    if not problems else f"{len(problems)} problem(s):")]
        lines += [f"  • {p}" for p in problems]
        lines.append(f"Pod copy: {len(copied)} file(s) into {dest}")
        if not out.ok:
            lines.append("  • the pod's output directory could not be copied: " + out.last_line())
        if not log.ok:
            lines.append("  • the ComfyUI log could not be copied: " + log.last_line())
        data = {"export_dir": str(dest), "copied": len(copied), "problems": problems}
        if problems or not out.ok:
            return ToolResult(text="\n".join(lines), data=data, artifacts=[str(dest)], is_error=True)
        pod.unexported = 0
        return ok("\n".join(lines), data=data, artifacts=[str(dest)])

    # pod_down ----------------------------------------------------------------

    async def down_preview(a: NoArgs) -> str:
        lines = ["Delete the pod. Billing stops. The Global Volume (models, ComfyUI code) is not touched.",
                 "", "  Command:  scripts/pod down   (deletes every pod named visual-generation)",
                 f"  Pod:      {pod.describe() if pod.up else 'not tracked in this session; whatever pod_status lists is deleted'}"]
        if pod.unexported:
            lines += ["", f"  {pod.unexported} render(s) since the last export. The pod's own output folder, input folder,",
                      "  logs and venv are on the container disk and are wiped. Images already saved locally are kept."]
        elif pod.up:
            lines += ["", "  Nothing rendered since the last export."]
        return "\n".join(lines)

    async def down_tool(a: NoArgs) -> ToolResult:
        r = await lc.down(state)
        if not r.ok:
            return fail(_failed("scripts/pod down", r) + "\nThe pod may still be billing. Check with pod_status.")
        pods, s = await lc.status(state)
        if s.ok and pods:
            return fail("scripts/pod down ran, but pod_status still lists: " + ", ".join(p.pod_id for p in pods)
                        + ". It may still be billing.")
        closed = await lc.close_tracking(state)
        check = "pod_status confirms none remain." if s.ok else "pod_status could not confirm it: " + s.last_line()
        if closed is None:
            return ok(f"Deleted. {check}", data={"cost_usd": 0.0})
        return ok(f"Deleted {closed['pod_id']}. {check} Uptime {closed['seconds'] / 60:.0f} min at "
                  f"${closed['rate_usd_per_hr']:.2f}/hr = ${closed['cost_usd']:.2f}, written to the GPU ledger"
                  + ("" if closed.get("start_observed", True) else " (the pod was already up when first seen, so this is a floor)")
                  + ".", data={"pod_id": closed["pod_id"], "uptime_cost_usd": closed["cost_usd"],
                              "uptime_seconds": closed["seconds"]})

    E = EffectClass.EXTERNAL_READ
    return [
        ToolSpec(name="pod_status", effect=E, input_model=NoArgs, handler=status_tool,
                 description="List RunPod pods (id, status, GPU count, $/hr) and what this session has set up on the "
                             "running one. Free."),
        ToolSpec(name="pod_up", effect=EffectClass.GPU_SPEND, input_model=UpArgs, handler=up_tool,
                 precheck=up_precheck, preview=up_preview, estimate_cost=up_estimate, preview_is_complete=True,
                 description="BILLING STARTS HERE. Create the pod (or reuse a running one). Pods are created and "
                             "deleted, never started or stopped. The director confirms. ComfyUI is not running afterward."),
        ToolSpec(name="pod_bootstrap", effect=E, input_model=NoArgs, handler=bootstrap_tool,
                 description="Copy comfyui-bootstrap to the pod and run it: installs ComfyUI if needed, rebuilds the "
                             "venv, starts the server. Needed on every new pod. Takes a few minutes."),
        ToolSpec(name="pod_tunnel", effect=E, input_model=NoArgs, handler=tunnel_tool,
                 description="Open the SSH tunnel to ComfyUI and check it answers on the pod and through the tunnel. "
                             "Returns the endpoint. Run again if a tunnel drops."),
        ToolSpec(name="model_sync", effect=EffectClass.MEMORY_WRITE, input_model=SyncArgs, handler=sync_tool,
                 precheck=sync_precheck, preview=sync_preview, preview_is_complete=True,
                 description="Rewrite the model registry to match THIS pod's volume. Runs once per new pod. Entries "
                             "absent from the pod are dropped; the director sees the dropped list and confirms."),
        ToolSpec(name="export_artifacts", effect=EffectClass.READ, input_model=NoArgs, handler=export_tool,
                 description="Before pod_down: check every output rendered this session has its image, submitted "
                             "graph and provenance file locally, and copy the pod's output folder and ComfyUI log."),
        ToolSpec(name="pod_down", effect=EffectClass.DESTRUCTIVE_LOCAL, input_model=NoArgs, handler=down_tool,
                 preview=down_preview, preview_is_complete=True,
                 description="Delete the pod: billing stops and its container disk is wiped. Records the uptime in "
                             "the GPU ledger. The director confirms. Run export_artifacts first."),
    ]
