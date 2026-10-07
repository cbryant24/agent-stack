"""`/pod rebuild`: the ten-step pod and volume rebuild runbook from
docs/v2-refinements/visual-generation-v2-refinements.md ("Infra resilience"), one checkpoint per
step. A failed step says which checkpoint failed; running the command again resumes there."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from visual_generation.chat.pod import lifecycle as lc
from visual_generation.chat.pod.runner import show
from visual_generation.chat.state import ChatState

STEPS = [
    "confirm the Global Volume", "check .env", "pod up", "check SSH keepalive", "read SSH connection info",
    "copy the bootstrap script", "run the bootstrap script", "open the tunnel", "smoke generation",
    "tear down or hand off",
]
POD_STEPS = range(3, 10)             # steps whose result belongs to one pod
VOLUME_STOP = (
    "the Global Volume was not confirmed. Without it there are no models to load, and rebuilding the models "
    "is outside this runbook. Nothing was created and nothing is billing"
)
SMOKE_PROMPT = "a red apple on a wooden table, soft daylight"
SMOKE_PLAN = {
    "question": "Does Z-Image render on this pod?", "baseline_attempt": None,
    "hypothesis": "A freshly bootstrapped pod renders one still after a cold model load.",
    "changed_variable": "the pod", "controlled_variables": ["template visual-workflow", "template default settings"],
    "acceptance_gate": "one image saved with its submitted graph and provenance file",
    "stop_rule": "one render", "session_cost_cap_usd": 0.5,
}

Step = tuple[bool, str]


def checkpoint_path(state: ChatState) -> Path:
    return state.data_dir / "pod-rebuild.json"


def load(state: ChatState) -> dict[str, Any]:
    path = checkpoint_path(state)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"pod_id": None, "steps": {}}


def save(state: ChatState, data: dict[str, Any]) -> None:
    path = checkpoint_path(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def passed(data: dict[str, Any], n: int) -> bool:
    return data["steps"].get(str(n), {}).get("status") == "passed"


def render_status(data: dict[str, Any]) -> str:
    rows = []
    for n, name in enumerate(STEPS, 1):
        step = data["steps"].get(str(n), {})
        rows.append(f"  {n:>2}. {name:<28} {step.get('status', 'not run'):<8} {step.get('detail', '')}"[:160])
    return "Pod rebuild" + (f" (pod {data['pod_id']})" if data.get("pod_id") else "") + ":\n" + "\n".join(rows)


def _tool_step(result: Any) -> Step:
    if result.data.get("rejected"):
        return False, "declined at the confirmation"
    return (not result.is_error), result.text.splitlines()[0][:200] if result.text else ""


async def run_rebuild(state: ChatState, ui: Any, args: list[str]) -> str:
    if args[:1] == ["status"]:
        return render_status(load(state))
    if args and args != ["restart"]:
        return "usage: /pod rebuild [status|restart]"
    dry = state.dry_run
    pod = state.pod
    data = {"pod_id": None, "steps": {}} if args == ["restart"] or dry else load(state)
    if all(passed(data, n) for n in range(1, 11)):
        data = {"pod_id": None, "steps": {}}                      # the last run finished: start a new one

    if not dry:
        pods, r = await lc.status(state)
        if r.ok:
            await lc.track(state, pods)
            if data.get("pod_id") != pod.pod_id:                  # that pod is gone, or a different one is up
                for n in POD_STEPS:
                    data["steps"].pop(str(n), None)
            if not pod.tunnel_alive:
                data["steps"].pop("8", None)                      # a tunnel belongs to the session that opened it

    async def need_ssh() -> Step:
        if pod.ssh_ip is not None:
            return True, f"{pod.ssh_ip}:{pod.ssh_port}"
        return await lc.read_ssh_info(state)

    async def step1() -> Step:
        if dry:
            return True, "would ask you to confirm the volume in the RunPod console"
        answer = await ui.choose(
            "Step 1. In the RunPod console, Volumes tab: does the Global Volume `stably_diffused` exist with "
            "models/ populated (about 85 GB)?", {"y": "yes, it is there", "n": "no, or not sure"})
        return (True, "confirmed by the director in the console") if answer == "y" else (False, VOLUME_STOP)

    async def step2() -> Step:
        problems = lc.env_problems(lc.env_names())
        if problems and dry:
            return True, "would stop here: " + "; ".join(problems)
        return (not problems), "; ".join(problems) or "RUNPOD_API_KEY and volume id present; template is safe"

    async def step3() -> Step:
        ok, detail = _tool_step(await ui.run_tool("pod_up", {}))
        if ok and not dry:
            data["pod_id"] = pod.pod_id
        return ok, detail

    async def step4() -> Step:
        if dry:
            return True, "would run: ssh -G root@<IP>"
        ok, detail = await lc.keepalive_config(state)
        note = "" if ok else (" (warning: add `ServerAliveInterval 30` and `ServerAliveCountMax 3` under `Host *` "
                              "in ~/.ssh/config; the chat's own ssh calls already pass both)")
        return True, detail + note

    async def step5() -> Step:
        if dry:
            return True, "would run: runpodctl pod get <pod-id> -o json"
        return await lc.read_ssh_info(state)

    async def step6() -> Step:
        if dry:
            return True, "would run: " + show(lc.scp_up_argv(state, lc.scripts_dir() / "comfyui-bootstrap", lc.REMOTE_BOOTSTRAP))
        ok, detail = await need_ssh()
        if not ok:
            return False, detail
        r = await lc.scp_bootstrap(state)
        return r.ok, "copied" if r.ok else f"scp failed (rc {r.rc}): {r.last_line()}"

    async def step7() -> Step:
        if dry:
            return True, "would run: " + show(lc.ssh_argv(state, "bash", lc.REMOTE_BOOTSTRAP))
        ok, detail = await need_ssh()
        if not ok:
            return False, detail
        ui.say("  installing and starting ComfyUI on the pod (a few minutes)")
        r = await lc.run_bootstrap(state)
        if r.ok:
            pod.bootstrapped = True
            return True, r.last_line()
        if lc.NO_MODELS_MARK in r.output:
            ui.say(lc.VOLUME_MISSING)
            await ui.run_tool("pod_down", {})
            return False, "the Global Volume is missing or empty; rebuilding the models is outside this runbook"
        return False, f"comfyui-bootstrap failed (rc {r.rc}): {r.last_line()}"

    async def step8() -> Step:
        return _tool_step(await ui.run_tool("pod_tunnel", {}))

    async def step9() -> Step:
        ui.say("  one still on visual-workflow; the first render on a new pod loads models for about 8 min")
        return _tool_step(await ui.run_tool("quick_generate", {"prompt": SMOKE_PROMPT, "attempt_plan": SMOKE_PLAN}))

    async def step10() -> Step:
        if dry:
            return True, "would ask: delete the pod now, or keep working with the idle check-in on"
        answer = await ui.choose(f"Step 10. The pod works ({pod.describe()}). Delete it now, or keep working?",
                                 {"d": "export and delete", "k": "keep working (idle check-in stays on)"})
        if answer != "d":
            return True, "kept running; the idle check-in is on"
        exported = await ui.run_tool("export_artifacts")
        if exported.is_error:
            return False, "the export reported problems, so the pod was not deleted and is still billing"
        down = await ui.run_tool("pod_down", confirmed=True)
        return (not down.is_error), "exported and deleted" if not down.is_error else down.text[:200]

    steps: list[Callable[[], Awaitable[Step]]] = [step1, step2, step3, step4, step5, step6, step7, step8, step9, step10]
    for n, (name, run) in enumerate(zip(STEPS, steps, strict=True), 1):
        if passed(data, n):
            ui.say(f"step {n}/10 {name}: already passed")
            continue
        ok, detail = await run()
        ui.say(f"step {n}/10 {name}: {'ok' if ok else 'FAILED'}. {detail}")
        if not dry:
            data["steps"][str(n)] = {"status": "passed" if ok else "failed", "detail": detail,
                                     "at": datetime.now(UTC).isoformat()}
            save(state, data)
        if not ok:
            return (f"Stopped at step {n} ({name}): {detail}. "
                    f"Fix it and run /pod rebuild to resume from step {n}.")
    return "[dry-run] walked all ten steps; nothing was created." if dry else "Pod rebuild complete: all ten steps passed."
