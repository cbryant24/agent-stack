"""Generation tools: the AttemptPlan gate, the cost cap, the approval rule, the endpoint health
check and its platform-layer finding, and "loading models" in place of silence. ComfyUI is an
httpx.MockTransport; nothing renders and nothing is spent."""

from __future__ import annotations

import itertools
import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import visual_generation.chat.tools.generation as gen_mod
from visual_generation.chat.tools import tool_pack
from visual_generation.models import VisualGeneration, VisualSource

from .conftest import Built  # type: ignore[import-not-found]
from .podkit import PLAN, Comfy, attach, spec, wire_generation, write_specs  # type: ignore[import-not-found]

pytestmark = pytest.mark.asyncio

ENDPOINT = "http://127.0.0.1:8188"


def tools(b: Built) -> dict[str, Any]:
    return {t.name: t for t in tool_pack(b.state)}


def ready(b: Built, tmp_path: Path, flux_template: Any, *, comfy: Comfy | None = None, n: int = 2,
          dry_run: bool = False) -> tuple[dict[str, Any], Comfy, Any, list[str]]:
    comfy = comfy or Comfy()
    audit, said = attach(b.state, tmp_path, comfy=comfy, dry_run=dry_run)
    wire_generation(b.store, flux_template)
    write_specs(b.state, [spec(f"s{i}") for i in range(1, n + 1)])
    return tools(b), comfy, audit, said


def args(t: dict[str, Any], **over: Any) -> Any:
    return t["generate"].input_model(**{"all_sections": True, "endpoint": ENDPOINT, "attempt_plan": PLAN, **over})


# ── the AttemptPlan gate ─────────────────────────────────────────────────────


async def test_generate_refuses_without_an_attempt_plan(build: Callable[..., Built], tmp_path: Path, flux_template: Any) -> None:
    b = build(allow_writes=True)
    t, comfy, _, _ = ready(b, tmp_path, flux_template)
    a = args(t, attempt_plan=None)
    refusal = await t["generate"].precheck(a)
    assert refusal == (
        "generate refused: no AttemptPlan. Before a paid run, give: question, baseline_attempt (or none), "
        "hypothesis, changed_variable, controlled_variables, acceptance_gate, stop_rule, session_cost_cap_usd.")
    assert (await t["generate"].handler(a)).is_error and comfy.submitted == [] and b.writes == []
    quick = t["quick_generate"]
    assert (await quick.precheck(quick.input_model(prompt="x"))).startswith("quick_generate refused: no AttemptPlan.")


async def test_generate_renders_under_the_plan_and_records_the_attempt(
    build: Callable[..., Built], tmp_path: Path, flux_template: Any
) -> None:
    b = build(allow_writes=True)
    t, comfy, audit, _ = ready(b, tmp_path, flux_template)
    a = args(t)
    assert await t["generate"].precheck(a) is None
    r = await t["generate"].handler(a)

    assert not r.is_error and r.data["status"] == "completed" and len(r.data["generation_ids"]) == 2
    assert len(comfy.submitted) == 2 and b.writes.count("upsert_generation") == 2
    for path in r.artifacts:                                  # Session 1's proof files, written by the call
        p = Path(path)
        assert p.is_file() and (p.parent / f"{p.stem}.graph.json").is_file() and (p.parent / f"{p.stem}.provenance.json").is_file()
    aid = r.data["attempt_id"]
    saved = json.loads((b.state.data_dir / "attempts" / f"{aid}.json").read_text())
    assert saved["plan"]["question"] == PLAN["question"] and saved["runs"][0]["generation_ids"] == r.data["generation_ids"]
    rec = next(x for x in audit.read() if x["kind"] == "attempt_plan")
    assert rec["attempt_id"] == aid and rec["plan"]["session_cost_cap_usd"] == 0.5
    assert b.state.ledger().cumulative() > 0 and b.state.pod.rendered


async def test_the_cost_cap_is_passed_as_max_session_cost_and_the_run_stops_at_it(
    build: Callable[..., Built], tmp_path: Path, flux_template: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = build(allow_writes=True)
    t, comfy, _, _ = ready(b, tmp_path, flux_template, n=3)
    seen: dict[str, Any] = {}
    real = gen_mod.spend_generation
    tick = itertools.count(0, 600).__next__                   # every clock read is ten minutes later

    async def spy(plan: Any, **kw: Any) -> Any:
        seen.update(kw)
        return await real(plan, **kw, clock=tick)

    monkeypatch.setattr(gen_mod, "spend_generation", spy)
    a = args(t, attempt_plan={**PLAN, "session_cost_cap_usd": 0.25})
    assert await t["generate"].precheck(a) is None
    r = await t["generate"].handler(a)

    assert seen["max_session_cost"] == 0.25
    assert r.data["status"] == "partial" and 0 < len(r.data["generation_ids"]) < 3
    assert f"Stopped at the cost cap ($0.25) after {len(r.data['generation_ids'])} of 3." in r.text
    assert len(comfy.submitted) == len(r.data["generation_ids"])


# ── the approval rule ────────────────────────────────────────────────────────


async def test_a_spec_sourced_from_an_unapproved_generation_is_skipped_unless_overridden(
    build: Callable[..., Built], tmp_path: Path, flux_template: Any
) -> None:
    disliked = VisualGeneration(caption="a", prompt="a", project="demo", reaction="disliked",
                                created_at="2026-01-01T00:00:01+00:00")
    liked = VisualGeneration(caption="b", prompt="b", project="demo", reaction="liked",
                             created_at="2026-01-01T00:00:02+00:00")
    b = build(gens=[disliked, liked], allow_writes=True)
    attach(b.state, tmp_path, comfy=Comfy())
    wire_generation(b.store, flux_template)
    write_specs(b.state, [
        spec("plain"),
        spec("from-bad", source=VisualSource(from_generation=disliked.entry_id)),
        spec("from-good", source=VisualSource(from_generation=liked.entry_id)),
    ])
    t = tools(b)

    r = await t["plan_generation"].handler(t["plan_generation"].input_model(all_sections=True))
    assert r.data["skipped"] == ["from-bad"] and set(r.data["specs"]) == {"plain", "from-good"}
    assert ('Skipped from-bad: source attempt-01 (' in r.text and 'has reaction "disliked", not a positive one. '
            "Pass allow_unapproved_sources to render it anyway." in r.text)

    r = await t["plan_generation"].handler(t["plan_generation"].input_model(all_sections=True, allow_unapproved_sources=True))
    assert r.data["skipped"] == [] and len(r.data["specs"]) == 3

    a = args(t)
    assert await t["generate"].precheck(a) is None
    panel = await t["generate"].preview(a)
    assert "Skipped (will not render)" in panel and "from-bad" in panel and "Render 2 spec(s)" in panel


# ── endpoint health: a platform-layer finding, before and after the prompt ───


async def test_no_pod_is_a_platform_finding_before_the_director_is_asked(
    build: Callable[..., Built], tmp_path: Path, flux_template: Any
) -> None:
    b = build(allow_writes=True)
    t, comfy, audit, _ = ready(b, tmp_path, flux_template)
    refusal = await t["generate"].precheck(args(t, endpoint=None))
    assert refusal == ("Platform-layer finding: ComfyUI is not reachable at the pod (no pod is up). Nothing was submitted "
                       "and no GPU time was spent by this call. Fix: pod_up, pod_bootstrap, pod_tunnel, model_sync.")
    finding = next(x for x in audit.read() if x["kind"] == "finding")
    assert finding["layer"] == "platform" and finding["tool"] == "generate" and comfy.requests == []


async def test_a_dropped_tunnel_is_reported_as_a_platform_finding_with_the_fix(
    build: Callable[..., Built], tmp_path: Path, flux_template: Any
) -> None:
    b = build(allow_writes=True)
    t, comfy, audit, _ = ready(b, tmp_path, flux_template)
    pod = b.state.pod
    pod.info, pod.endpoint = SimpleNamespace(pod_id="pod-abc", cost_per_hr=0.6), ENDPOINT
    pod.tunnel = SimpleNamespace(returncode=None)
    a = args(t, endpoint=None)                                  # default: the tunnel
    assert await t["generate"].precheck(a) is None              # healthy when the director is asked

    comfy.down, pod.tunnel.returncode = True, 255               # ... and it drops while they read the panel
    r = await t["generate"].handler(a)
    assert r.is_error and r.data["layer"] == "platform" and comfy.submitted == []
    assert r.text == (f"Platform-layer finding: ComfyUI is not reachable at {ENDPOINT} (the SSH tunnel exited (rc 255)). "
                      "Nothing was submitted and no GPU time was spent by this call. ComfyUI on the pod keeps running. "
                      "Fix: pod_tunnel, then generate again.")
    assert [x["layer"] for x in audit.read() if x["kind"] == "finding"] == ["platform"]
    assert b.writes == []


async def test_a_drop_mid_run_keeps_what_rendered_and_is_still_a_platform_finding(
    build: Callable[..., Built], tmp_path: Path, flux_template: Any
) -> None:
    b = build(allow_writes=True)
    comfy = Comfy()
    comfy.drop_after_submits = 1
    t, _, audit, _ = ready(b, tmp_path, flux_template, comfy=comfy, n=3)
    a = args(t)
    assert await t["generate"].precheck(a) is None
    r = await t["generate"].handler(a)
    assert r.is_error and r.data["status"] == "unreachable" and len(r.data["generation_ids"]) == 1
    assert "unreachable: rendered 1 of 3" in r.text and "Platform-layer finding" in r.text
    assert "it stopped answering during the run" in r.text and "no GPU time was spent" not in r.text
    assert any(x["kind"] == "finding" for x in audit.read()) and len(r.artifacts) == 1


# ── "loading models", not silence ────────────────────────────────────────────


async def test_a_slow_first_render_reports_loading_models_and_is_not_a_failure(
    build: Callable[..., Built], tmp_path: Path, flux_template: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = build(allow_writes=True)
    t, comfy, _, said = ready(b, tmp_path, flux_template, comfy=Comfy(empty_polls=4), n=1)
    seen: dict[str, Any] = {}
    real = gen_mod.spend_generation
    tick = itertools.count(0, 20).__next__                      # 20 s per clock read: a multi-minute cold load

    async def spy(plan: Any, **kw: Any) -> Any:
        seen.update(kw)
        return await real(plan, **kw, clock=tick, poll_interval=0)

    monkeypatch.setattr(gen_mod, "spend_generation", spy)
    a = args(t)
    assert await t["generate"].precheck(a) is None
    assert 'expect "loading models" for about 8 min' in await t["generate"].preview(a)
    r = await t["generate"].handler(a)

    assert not r.is_error and r.data["status"] == "completed" and len(r.data["generation_ids"]) == 1
    assert seen["poll_timeout"] == 1800.0                       # the cold-load allowance, not the 600 s default
    assert said and all(s.startswith("loading models: first render on this pod, job is running on the pod") for s in said)
    assert "about 8 min is normal" in said[0] and "/queue" in comfy.requests

    said.clear()                                                # the pod is warm now: a short timeout, no "loading"
    comfy.empty_polls = 2
    assert await t["generate"].precheck(a) is None
    await t["generate"].handler(a)
    assert seen["poll_timeout"] == 600.0 and all(s.startswith("rendering:") for s in said)


async def test_a_job_that_left_the_queue_is_said_plainly(build: Callable[..., Built], tmp_path: Path, flux_template: Any) -> None:
    b = build()
    comfy = Comfy()
    comfy.queue_running = False
    _, said = attach(b.state, tmp_path, comfy=comfy)
    on_wait = gen_mod.loading_notifier(b.state, comfy.client(ENDPOINT), cold=True)
    await on_wait("pid-9", 5.0)
    assert said == []                                           # too early to say anything
    await on_wait("pid-9", 20.0)
    assert "no longer in the pod's queue and has produced no output yet (0m20s)" in said[0]


# ── the panel ────────────────────────────────────────────────────────────────


async def test_the_generate_confirm_panel_text(build: Callable[..., Built], tmp_path: Path, flux_template: Any) -> None:
    b = build(allow_writes=True)
    t, _, _, _ = ready(b, tmp_path, flux_template, n=3)
    b.store.recent_generation_costs.return_value = [0.03, 0.0354]
    b.state.ledger().record_session(1.2345)
    b.state.ledger().set_budget(10.0)
    a = args(t)
    assert t["generate"].preview_is_complete and await t["generate"].precheck(a) is None
    panel = await t["generate"].preview(a)
    aid = b.state.shown["generate"]["attempt_id"]
    assert aid.startswith("demo-") and panel == "\n".join([
        f"Render 3 spec(s) from {b.state.batch_path()}",
        f"on {ENDPOINT}",
        "",
        f"Attempt plan  ({aid})",
        "  Question:     Does each saved seed equal the seed in the submitted graph?",
        "  Baseline:     none",
        "  Hypothesis:   Random seeds differ and the fixed seed is honored.",
        "  Changed:      seed strategy",
        "  Controlled:   template flux-txt2img; prompt",
        "  Accept when:  evaluation-charter.md Gate 0",
        "  Stop rule:    stop after 3 renders or the first mismatch",
        "  Cost cap:     $0.50, hard. The run stops before the render that would pass it.",
        "",
        "Cost",
        "  Specs to render:   3",
        "  Per-run estimate:  $0.0327 (learned from recent runs)",
        "  GPU rate:          $0.69/hr (default; no pod rate known)",
        "  Session estimate:  $0.0981",
        "  Local cumulative:  $1.2345 inference estimates, $0.00 pod uptime",
        "  Declared budget:   $8.77 remaining",
        "",
        "Endpoint",
        "  ComfyUI answered /system_stats just now.",
        '  First render on this pod: expect "loading models" for about 8 min',
        "  before the first image. That is not a hang.",
    ])
    assert t["generate"].estimate_cost(a) == pytest.approx(0.0981)


async def test_dry_run_shows_the_panel_without_touching_the_endpoint(
    build: Callable[..., Built], tmp_path: Path, flux_template: Any
) -> None:
    b = build(allow_writes=True)
    t, comfy, _, _ = ready(b, tmp_path, flux_template, dry_run=True)
    comfy.down = True                                            # there is no pod in a dry-run
    a = args(t, endpoint=None)
    assert await t["generate"].precheck(a) is None
    panel = await t["generate"].preview(a)
    assert "dry-run: endpoint not checked" in panel and "on the pod (no endpoint yet)" in panel
    assert comfy.requests == []
    assert (await t["generate"].precheck(args(t, attempt_plan=None))).startswith("generate refused")   # still required


# ── quick_generate, gpu_ledger, and the link to evaluations ──────────────────


async def test_quick_generate_renders_one_still_and_writes_no_memory(
    build: Callable[..., Built], tmp_path: Path, flux_template: Any
) -> None:
    b = build()                                                  # stores that fail loudly on any write
    t, comfy, audit, _ = ready(b, tmp_path, flux_template)
    q = t["quick_generate"]
    a = q.input_model(prompt="a red apple", template_name="flux-txt2img", seed=5, endpoint=ENDPOINT, attempt_plan=PLAN)
    assert await q.precheck(a) is None
    panel = await q.preview(a)
    assert "Render 1 still with template flux-txt2img" in panel and "Attempt plan" in panel and "seed=5" in panel
    r = await q.handler(a)
    assert not r.is_error and Path(r.data["asset_path"]).is_file() and r.data["seed"] == 5
    assert b.writes == [] and len(comfy.submitted) == 1
    assert any(x["kind"] == "attempt_plan" and x["tool"] == "quick_generate" for x in audit.read())
    assert b.state.pod.output_paths == [r.data["asset_path"]]


async def test_gpu_ledger_keeps_uptime_and_inference_apart(build: Callable[..., Built], tmp_path: Path) -> None:
    b = build()
    attach(b.state, tmp_path)
    ledger = b.state.ledger()
    ledger.record_session(0.098)
    ledger.open_pod_uptime("pod-1", 0.69, started_at="2026-10-07T17:00:00+00:00")
    ledger.close_pod_uptime("pod-1", ended_at="2026-10-07T17:30:00+00:00")
    t = tools(b)
    r = await t["gpu_ledger"].handler(t["gpu_ledger"].input_model())
    assert "Inference estimates, cumulative:  $0.0980" in r.text and "Pod uptime, closed pods:          $0.34" in r.text
    assert "pod-1  30 min at $0.69/hr = $0.34" in r.text and "not added together" in r.text
    assert r.data["pod_uptime_usd"] == pytest.approx(0.345) and r.data["inference_cumulative_usd"] == pytest.approx(0.098)


async def test_an_evaluation_is_linked_to_the_attempt_that_rendered_it(
    build: Callable[..., Built], tmp_path: Path, flux_template: Any
) -> None:
    from visual_generation.chat.attempt import AttemptPlan, save_attempt

    from .conftest import make_gens  # type: ignore[import-not-found]

    gens = make_gens(3)
    b = build(gens=gens, allow_writes=True)
    attach(b.state, tmp_path)
    save_attempt(b.state, "demo-2026-10-07-3f9a", AttemptPlan(**PLAN), tool="generate", generation_ids=[gens[1].entry_id])
    t = tools(b)
    ev = t["record_evaluation"]
    a = ev.input_model(generation="attempt-02", raw_feedback="seed matches", reaction="liked")
    assert "Attempt plan: demo-2026-10-07-3f9a" in await ev.preview(a)
    r = await ev.handler(a)
    (entry,) = b.evals
    assert r.data["attempt_id"] == entry.attempt_id == "demo-2026-10-07-3f9a" and entry.question == PLAN["question"]
