"""The pod and the REPL's life cycle: startup check, drain prompt, review warning, idle check-in,
exit question, `/pod rebuild`, and a dry-run of the whole sequence. Real tool pack, real
agent-shell Session, scripted engine and scripted director; fake scripts; no pod."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from agent_shell.config import ShellSettings
from agent_shell.engine.fake import Call, FakeEngine, Say
from agent_shell.guard.gate import AutoConfirmer
from agent_shell.session.api import Session
from agent_shell.testing import drain
from agent_shell.ui import ScriptedUI

import visual_generation.chat.pod.hooks as hooks_mod
import visual_generation.chat.pod.lifecycle as lc
from visual_generation.chat.config import build_chat_config
from visual_generation.chat.pod.hooks import PodHooks
from visual_generation.chat.pod.rebuild import checkpoint_path, load

from .conftest import Built  # type: ignore[import-not-found]
from .podkit import PLAN, Comfy, spec, wire_generation, write_specs  # type: ignore[import-not-found]

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lc, "TUNNEL_SETTLE_SEC", 0.01)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def started(b: Built, tmp_path: Path, *, script: list[list[Say | Call]] | None = None, dry_run: bool = False,
                  confirmer: AutoConfirmer | None = None, comfy: Comfy | None = None) -> Session:
    b.state.session = None
    b.state.comfy = (comfy or Comfy()).client
    s = Session(build_chat_config(b.state),
                ShellSettings(agent_data_dir=tmp_path / "shell", dry_run=dry_run, gpu_budget_usd=5.0),
                FakeEngine(script or []), confirmer=confirmer or AutoConfirmer())
    b.state.session = s
    await s.start()
    return s


def hooks(b: Built) -> tuple[PodHooks, Clock]:
    clock = Clock()
    return PodHooks(b.state, clock=clock), clock


# ── startup ──────────────────────────────────────────────────────────────────


async def test_startup_reports_a_pod_that_is_already_running(build: Callable[..., Built], tmp_path: Path, fake_scripts: Any) -> None:
    b = build()
    s = await started(b, tmp_path)
    fake_scripts.pod_exists()
    h, _ = hooks(b)
    ui = ScriptedUI(s)
    await h.on_start(ui)
    assert len(ui.said) == 1 and ui.said[0].startswith("A pod is already running: pod-abc, up at least 0 min")
    assert "It is billing now." in ui.said[0]
    entry = b.state.ledger().open_pod_entry()                    # adopted: tracked from now, start not observed
    assert entry["pod_id"] == "pod-abc" and entry["start_observed"] is False and b.state.pod.up
    assert h.idle_due_in() == hooks_mod.CHECKIN_INTERVAL


async def test_startup_is_quiet_with_no_pod_and_closes_a_stale_ledger_entry(build: Callable[..., Built], tmp_path: Path) -> None:
    b = build()
    s = await started(b, tmp_path)
    b.state.ledger().open_pod_uptime("pod-gone", 0.69)           # a pod deleted outside the chat
    h, _ = hooks(b)
    ui = ScriptedUI(s)
    await h.on_start(ui)
    (entry,) = b.state.ledger().entries("pod_uptime")
    assert ui.said == [] and entry["ended_at"] and entry["end_observed"] is False and h.idle_due_in() is None


async def test_startup_carries_on_when_status_is_unavailable(
    build: Callable[..., Built], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = build()
    s = await started(b, tmp_path)
    monkeypatch.setenv("FAKE_POD_STATUS", "fail")
    ui = ScriptedUI(s)
    await hooks(b)[0].on_start(ui)
    assert ui.said == ["pod status unavailable (error: runpodctl not found on PATH.); carrying on without it"]


# ── drain, review, idle, exit ────────────────────────────────────────────────


async def up(b: Built, tmp_path: Path, **kw: Any) -> tuple[Session, PodHooks, Clock]:
    s = await started(b, tmp_path, **kw)
    r = await s.run_tool("pod_up", {}, confirmer=AutoConfirmer("accept"))
    assert not r.is_error, r.text
    h, clock = hooks(b)
    b.state.pod.last_checkin = clock()
    return s, h, clock


async def test_a_drained_batch_prompts_to_export_and_delete(build: Callable[..., Built], tmp_path: Path, fake_scripts: Any) -> None:
    b = build()
    s, h, _ = await up(b, tmp_path)
    await s.run_tool("pod_bootstrap")
    b.state.pod.drain_pending = True
    ui = ScriptedUI(s, choices=["y"])
    await h.on_turn_end(ui)
    assert ui.asked[0].startswith("Batch drained. Export artifacts and delete the pod now?")
    assert fake_scripts.ran("pod down") and not b.state.pod.up and b.state.ledger().open_pod_entry() is None
    assert s.audit is not None
    decisions = {r["tool"]: r["decision"] for r in s.audit.read() if r.get("kind") == "tool_call"}
    assert decisions["export_artifacts"] == "allow" and decisions["pod_down"] == "proposal_accept"
    assert ui.requests == []                                     # the answer was the confirmation: no second prompt


async def test_declining_the_drain_prompt_warns_and_keeps_warning_during_review(
    build: Callable[..., Built], tmp_path: Path, fake_scripts: Any
) -> None:
    b = build()
    s, h, clock = await up(b, tmp_path)
    pod = b.state.pod
    pod.drain_pending, pod.rendered = True, True
    ui = ScriptedUI(s, choices=["n"])
    await h.on_turn_end(ui)
    assert ui.said == ["Pod stays up while you review. The repo rule is not to leave a pod running during review."]
    assert pod.up and fake_scripts.ran("pod down") == []
    await h.on_turn_end(ui)                                      # right away: no repeat
    assert len(ui.said) == 1
    clock.now += 301
    await h.on_turn_end(ui)
    assert len(ui.said) == 2 and ui.said[1].startswith("Pod is up while you review: pod-abc")


async def test_the_idle_check_in_keeps_the_pod_when_answered(build: Callable[..., Built], tmp_path: Path, fake_scripts: Any) -> None:
    b = build()
    s, h, clock = await up(b, tmp_path)
    assert h.idle_due_in() == 1800.0
    clock.now += 1800
    assert h.idle_due_in() == 0.0
    ui = ScriptedUI(s, choices=["k"])
    await h.checkin(ui)
    assert "Pod check-in: pod-abc" in ui.asked[0] and "No answer in 3 min exports and deletes it." in ui.asked[0]
    assert b.state.pod.up and h.idle_due_in() == 1800.0 and fake_scripts.ran("pod down") == []


async def test_an_unanswered_check_in_exports_then_deletes_the_pod(build: Callable[..., Built], tmp_path: Path, fake_scripts: Any) -> None:
    b = build()
    s, h, clock = await up(b, tmp_path)
    await s.run_tool("pod_bootstrap")
    clock.now += 1800
    ui = ScriptedUI(s, choices=[None])                           # nobody answered within the grace period
    await h.on_turn_end(ui)                                      # the turn-end path runs the check-in when due
    assert ui.said == ["No answer in 3 min: exporting, then deleting the pod, as scripts/pod watch would."]
    log = fake_scripts.log()
    scp = next(i for i, ln in enumerate(log) if ln.startswith("scp -r"))
    down = next(i for i, ln in enumerate(log) if ln.startswith("pod down"))
    assert scp < down and not b.state.pod.up
    (entry,) = b.state.ledger().entries("pod_uptime")
    assert entry["ended_at"] and entry["end_observed"] is True


async def test_a_check_in_never_deletes_a_pod_with_a_render_in_flight(build: Callable[..., Built], tmp_path: Path, fake_scripts: Any) -> None:
    b = build()
    s, h, clock = await up(b, tmp_path)
    clock.now += 1800
    b.state.pod.in_flight = True
    ui = ScriptedUI(s)                                           # any question would fail the test
    await h.checkin(ui)
    assert b.state.pod.up and h.idle_due_in() == 60.0 and fake_scripts.ran("pod down") == []


async def test_exit_with_a_pod_up_asks_first(
    build: Callable[..., Built], tmp_path: Path, fake_scripts: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = build()
    s, h, _ = await up(b, tmp_path)
    monkeypatch.setattr(lc, "can_watch", lambda: True)
    ui = ScriptedUI(s, choices=["l"])
    await h.on_exit(ui)
    assert ui.asked[0].startswith("A pod is still running: pod-abc") and "keeps billing after you exit" in ui.asked[0]
    assert ui.said == ["Pod left running with no watchdog. Delete it with: ./scripts/pod down"] and b.state.pod.up

    ui = ScriptedUI(s, choices=["w"])
    await h.on_exit(ui)
    assert "scripts/pod watch started" in ui.said[0]
    assert s.audit is not None
    spawned = [r for r in s.audit.read() if r.get("label") == "pod watch"]
    assert spawned and spawned[0]["argv"] == [str(fake_scripts.dir / "pod"), "watch"]

    await s.run_tool("pod_bootstrap")
    ui = ScriptedUI(s, choices=["d"])
    await h.on_exit(ui)
    assert not b.state.pod.up and fake_scripts.ran("pod down")
    ui = ScriptedUI(s)                                           # no pod: no question at all
    await h.on_exit(ui)
    assert ui.asked == []


async def test_a_failed_export_stops_an_attended_delete(build: Callable[..., Built], tmp_path: Path, fake_scripts: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    b = build()
    s, h, _ = await up(b, tmp_path)
    await s.run_tool("pod_bootstrap")
    monkeypatch.setenv("FAKE_SCP", "fail")
    ui = ScriptedUI(s, choices=["d"])
    await h.on_exit(ui)
    assert "the pod was NOT deleted" in ui.said[0] and b.state.pod.up and fake_scripts.ran("pod down") == []


# ── /pod rebuild ─────────────────────────────────────────────────────────────


async def rebuild(b: Built, s: Session, ui: ScriptedUI, *args: str) -> str:
    return await s.config.slash_commands["/pod"](["rebuild", *args], ui)


async def test_rebuild_walks_ten_checkpoints_and_resumes_at_the_failed_step(
    build: Callable[..., Built], tmp_path: Path, fake_scripts: Any, monkeypatch: pytest.MonkeyPatch, flux_template: Any
) -> None:
    b = build()
    s = await started(b, tmp_path)
    wire_generation(b.store, flux_template)
    b.store.get_template_by_name.side_effect = lambda name: flux_template      # stands in for visual-workflow

    monkeypatch.setenv("FAKE_BOOTSTRAP", "fail")
    ui = ScriptedUI(s, choices=["y"], decisions=["accept"])                    # volume yes; pod_up yes
    out = await rebuild(b, s, ui)
    assert out == ("Stopped at step 7 (run the bootstrap script): comfyui-bootstrap failed (rc 1): error: ComfyUI process "
                   "exited immediately. Fix it and run /pod rebuild to resume from step 7.")
    data = load(b.state)
    assert [data["steps"][str(n)]["status"] for n in range(1, 8)] == ["passed"] * 6 + ["failed"]
    assert data["pod_id"] == "pod-abc" and checkpoint_path(b.state).is_file()
    assert "7. run the bootstrap script" in await rebuild(b, s, ScriptedUI(s), "status")

    monkeypatch.setenv("FAKE_BOOTSTRAP", "ok")
    before = len(fake_scripts.ran("op run"))
    ui = ScriptedUI(s, choices=["d"], decisions=["accept"])                    # smoke render yes; then delete
    out = await rebuild(b, s, ui)
    assert out == "Pod rebuild complete: all ten steps passed."
    assert [ln for ln in ui.said if "already passed" in ln][0] == "step 1/10 confirm the Global Volume: already passed"
    assert sum("already passed" in ln for ln in ui.said) == 6                  # steps 1-6 were not run again
    assert len(fake_scripts.ran("op run")) == before                           # no second pod_up
    assert all(load(b.state)["steps"][str(n)]["status"] == "passed" for n in range(1, 11))
    assert ui.requests[0].tool == "quick_generate" and "Does Z-Image render on this pod?" in (ui.requests[0].preview or "")
    assert not b.state.pod.up and fake_scripts.ran("pod down")
    assert any("serveraliveinterval" not in ln and " -G " in f" {ln} " for ln in fake_scripts.ran("ssh "))


async def test_rebuild_stops_at_step_one_when_the_volume_is_not_confirmed(build: Callable[..., Built], tmp_path: Path, fake_scripts: Any) -> None:
    b = build()
    s = await started(b, tmp_path)
    out = await rebuild(b, s, ScriptedUI(s, choices=["n"]))
    assert out.startswith("Stopped at step 1 (confirm the Global Volume): the Global Volume was not confirmed.")
    assert "rebuilding the models is outside this runbook. Nothing was created and nothing is billing." in out
    assert fake_scripts.ran("op ") == [] and fake_scripts.ran("pod up") == []


async def test_rebuild_stops_on_an_unsafe_template(build: Callable[..., Built], tmp_path: Path, fake_scripts: Any) -> None:
    b = build()
    s = await started(b, tmp_path)
    fake_scripts.env.write_text("RUNPOD_API_KEY=op://x\nIMAGE_NETWORK_VOLUME_ID=v\nTEMPLATE_ID=cnne9dp3rt\n")
    out = await rebuild(b, s, ScriptedUI(s, choices=["y"]))
    assert out.startswith("Stopped at step 2 (check .env): TEMPLATE_ID=cnne9dp3rt is the crash-looping ComfyUI template")
    assert fake_scripts.ran("pod up") == []


async def test_rebuild_reports_a_missing_volume_found_on_the_pod_and_offers_to_delete(
    build: Callable[..., Built], tmp_path: Path, fake_scripts: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = build()
    s = await started(b, tmp_path)
    monkeypatch.setenv("FAKE_BOOTSTRAP", "no_models")
    ui = ScriptedUI(s, choices=["y"], decisions=["accept", "accept"])          # pod_up, then pod_down
    out = await rebuild(b, s, ui)
    assert out.startswith("Stopped at step 7 (run the bootstrap script): the Global Volume is missing or empty")
    assert any("still billing" in ln for ln in ui.said) and ui.requests[-1].tool == "pod_down"
    assert not b.state.pod.up and fake_scripts.ran("pod down")


# ── dry-run walks everything and creates nothing ─────────────────────────────

SEQUENCE = ["pod_status", "pod_up", "pod_bootstrap", "pod_tunnel", "model_sync", "generate", "export_artifacts", "pod_down"]


async def test_dry_run_walks_the_standard_sequence_without_creating_a_pod(
    build: Callable[..., Built], tmp_path: Path, fake_scripts: Any, flux_template: Any
) -> None:
    b = build()                                                                # stores fail loudly on any write
    comfy = Comfy()
    comfy.down = True                                                          # there is no pod to answer
    wire_generation(b.store, flux_template)
    write_specs(b.state, [spec("s1"), spec("s2")])
    calls = [Call(name=n, args={"all_sections": True, "attempt_plan": PLAN} if n == "generate" else {}) for n in SEQUENCE]
    c = AutoConfirmer()
    s = await started(b, tmp_path, script=[calls], dry_run=True, confirmer=c, comfy=comfy)
    events = await drain(s, "run the standard sequence")

    results = {e.name: e.result for e in events if hasattr(e, "result")}
    assert list(results) == SEQUENCE and not any(r.is_error for r in results.values())
    for name in SEQUENCE[1:]:
        assert results[name].data.get("dry_run") is True, name
    assert results["pod_up"].text.startswith("[dry-run] would run pod_up: Create a RunPod pod.")
    assert "Attempt plan" in results["generate"].text and "dry-run: endpoint not checked" in results["generate"].text
    assert c.requests == [] and b.writes == [] and comfy.requests == []
    log = fake_scripts.log()
    assert log and all(ln.startswith("pod status") for ln in log)             # the only thing that ran was a read
    assert b.state.ledger().entries() == [] and not b.state.pod.up

    out = await rebuild(b, s, ScriptedUI(s))                                   # no question is asked in a dry-run
    assert out == "[dry-run] walked all ten steps; nothing was created."
    assert not checkpoint_path(b.state).exists()
    assert all(ln.startswith("pod status") for ln in fake_scripts.log())
    assert json.dumps(fake_scripts.log()).count("pod up") == 0
