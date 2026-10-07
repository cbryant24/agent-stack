"""Generation tools: the chat's GPU spend.

`plan_generation` is free; `generate` and `quick_generate` spend and go through the gate. A paid
call is refused without an AttemptPlan, checks the endpoint before it asks the director and again
before it submits, and reports a long first render as "loading models" instead of going silent.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from agent_shell.tools.registry import EffectClass, ToolResult, ToolSpec
from pydantic import BaseModel, Field

from visual_generation.chat.attempt import REFUSAL, AttemptPlan, attempt_id, render_attempt, save_attempt
from visual_generation.chat.state import ChatState
from visual_generation.chat.tools._common import fail, ok, project_note, resolver_for
from visual_generation.comfyui_client import ComfyUIClient, ComfyUIError
from visual_generation.constants import (
    COLD_LOAD_POLL_TIMEOUT_SEC,
    DEFAULT_GPU_RATE_USD_PER_HR,
    DEFAULT_PER_RUN_MINUTES,
    DEFAULT_POLL_TIMEOUT_SEC,
    DEFAULT_QUICK_IMAGE_TEMPLATE,
    LOADING_NOTICE_AFTER_SEC,
    LOADING_NOTICE_EVERY_SEC,
    POSITIVE_REACTIONS,
)
from visual_generation.curation import parse_lora
from visual_generation.generate import GenerationPlan, plan_generation, spend_generation
from visual_generation.lora_guard import strength_warnings
from visual_generation.quick import (
    QuickInvalidSpec,
    QuickLoraUnsafe,
    QuickSeedUnmapped,
    QuickSourceError,
    QuickTemplateNotFound,
    quick_generate,
)

PLATFORM = (
    "Platform-layer finding: ComfyUI is not reachable at {endpoint} ({cause}). Nothing was submitted and no "
    "GPU time was spent by this call. {fix}"
)
COLD_LOAD_NOTE = "about 8 min is normal"


class PlanArgs(BaseModel):
    project: str | None = Field(default=None, description="Project slug (defaults to the active project).")
    batch_path: str | None = Field(default=None, description="A batch file elsewhere; default is the project's visual-batch.md.")
    section_id: str | None = Field(default=None, description="Render one spec by id.")
    all_sections: bool = Field(default=False, description="Render every spec in the batch.")
    allow_unapproved_sources: bool = Field(
        default=False, description="Render a spec whose source generation has no positive reaction. "
                                   "Only when the director said so.")


class GenerateArgs(PlanArgs):
    endpoint: str | None = Field(default=None, description="ComfyUI URL. Default: the tunnel pod_tunnel opened.")
    attempt_plan: AttemptPlan | None = Field(default=None, description="Required. The experiment this run is.")


class QuickArgs(BaseModel):
    prompt: str
    template_name: str | None = Field(default=None, description=f"Default: {DEFAULT_QUICK_IMAGE_TEMPLATE}.")
    negative_prompt: str | None = None
    seed: int | None = Field(default=None, description="Fixed seed; default random.")
    width: int | None = None
    height: int | None = None
    steps: int | None = None
    cfg: float | None = None
    sampler: str | None = None
    scheduler: str | None = None
    loras: list[str] = Field(default_factory=list, description="NAME[:STRENGTH], registry names.")
    endpoint: str | None = Field(default=None, description="ComfyUI URL. Default: the tunnel pod_tunnel opened.")
    attempt_plan: AttemptPlan | None = Field(default=None, description="Required. The experiment this run is.")


class NoArgs(BaseModel):
    pass


def _key(a: BaseModel) -> str:
    return json.dumps(a.model_dump(mode="json"), sort_keys=True)


def _clock(seconds: float) -> str:
    return f"{int(seconds) // 60}m{int(seconds) % 60:02d}s"


# ── endpoint health ──────────────────────────────────────────────────────────


def resolve_endpoint(state: ChatState, given: str | None) -> str | None:
    return given or state.pod.endpoint


async def endpoint_problem(state: ChatState, endpoint: str | None) -> str | None:
    """None when ComfyUI answers at `endpoint`; otherwise the platform-layer finding, with the fix
    chosen from what the session knows (no pod, no tunnel, a tunnel that died, a silent ComfyUI)."""
    pod = state.pod
    if endpoint is None:
        if not pod.up:
            cause, fix = "no pod is up", "Fix: pod_up, pod_bootstrap, pod_tunnel, model_sync."
        else:
            cause, fix = "no tunnel is open", "Fix: pod_tunnel."
        return PLATFORM.format(endpoint="the pod", cause=cause, fix=fix)
    try:
        await state.comfy(endpoint).system_stats()
        return None
    except ComfyUIError as exc:
        if endpoint == pod.endpoint and pod.tunnel is not None and not pod.tunnel_alive:
            cause = f"the SSH tunnel exited (rc {pod.tunnel.returncode})"
            fix = "ComfyUI on the pod keeps running. Fix: pod_tunnel, then generate again."
        elif endpoint == pod.endpoint and pod.tunnel_alive:
            cause = "the tunnel is open but ComfyUI does not answer"
            fix = "Fix: pod_bootstrap, then pod_tunnel."
        else:
            cause = type(exc).__name__
            fix = "Fix: check that a pod is up and the endpoint is right (pod_status, pod_tunnel)."
        return PLATFORM.format(endpoint=endpoint, cause=cause, fix=fix)


def record_finding(state: ChatState, tool: str, text: str) -> None:
    state.audit(kind="finding", layer="platform", tool=tool, statement=text)


# ── "loading models", not silence ────────────────────────────────────────────


async def _job_state(client: ComfyUIClient, prompt_id: str) -> str:
    try:
        q = await client.queue()
    except ComfyUIError:
        return "unknown"
    for name, label in (("queue_running", "running"), ("queue_pending", "queued")):
        if any(len(item) > 1 and item[1] == prompt_id for item in q.get(name) or []):
            return label
    return "gone"


def loading_notifier(state: ChatState, client: ComfyUIClient, *, cold: bool) -> Callable[[str, float], Awaitable[None]]:
    """Speak after LOADING_NOTICE_AFTER_SEC with nothing rendered, then every LOADING_NOTICE_EVERY_SEC.
    A job the pod still holds is a model load (or the render itself), never reported as a hang."""
    last_at = {"": 0.0}                    # prompt id -> when it was last reported on

    async def on_wait(prompt_id: str, elapsed: float) -> None:
        at = last_at.get(prompt_id, 0.0)
        due = LOADING_NOTICE_AFTER_SEC if not at else at + LOADING_NOTICE_EVERY_SEC
        if elapsed < due:
            return
        last_at[prompt_id] = max(elapsed, 0.001)
        where = await _job_state(client, prompt_id)
        if where == "gone":
            state.notify(f"the job is no longer in the pod's queue and has produced no output yet ({_clock(elapsed)}). "
                         "If the next check says the same, read the ComfyUI log (export_artifacts copies it).")
        elif cold and not state.pod.rendered:
            held = "its queue state could not be read" if where == "unknown" else f"job is {where} on the pod"
            state.notify(f"loading models: first render on this pod, {held}, {_clock(elapsed)} elapsed ({COLD_LOAD_NOTE})")
        else:
            state.notify(f"rendering: job is {where} on the pod, {_clock(elapsed)} elapsed")

    return on_wait


# ── the plan, and the panel that shows it ────────────────────────────────────


def _batch_path(state: ChatState, a: PlanArgs) -> Path:
    return Path(a.batch_path).expanduser() if a.batch_path else state.batch_path(a.project)


def _rate(state: ChatState) -> tuple[float, str]:
    if state.pod.rate is not None:
        return state.pod.rate, "this pod"
    return DEFAULT_GPU_RATE_USD_PER_HR, "default; no pod rate known"


async def build_plan(state: ChatState, a: PlanArgs) -> tuple[Path, GenerationPlan]:
    """`plan_generation`, then the approval rule: a spec sourced from a prior generation is skipped
    unless that generation has a positive reaction (or the override flag is set)."""
    path = _batch_path(state, a)
    if not path.is_file():
        raise ValueError(f"No batch file at {path}. `draft` creates it.")
    store, memory = state.stores()
    rate, _ = _rate(state)
    plan = await plan_generation(path, section_id=a.section_id, all_sections=a.all_sections, gpu_rate=rate,
                                 store=store, memory_store=memory)
    if a.allow_unapproved_sources:
        return path, plan
    resolver = await resolver_for(state, a.project)
    kept = []
    for sp in plan.plans:
        src = sp.spec.source.from_generation if sp.spec.source else None
        gen = await store.get_generation(src) if src else None
        if src and (gen is None or gen.reaction not in POSITIVE_REACTIONS):
            what = "was not found" if gen is None else f'has reaction "{gen.reaction}", not a positive one'
            plan.skipped.append(sp.spec.spec_id)
            plan.skip_reasons[sp.spec.spec_id] = (
                f"Skipped {sp.spec.spec_id}: source {resolver.display(src)} {what}. "
                "Pass allow_unapproved_sources to render it anyway.")
        else:
            kept.append(sp)
    plan.plans = kept
    return path, plan


def _is_identity(state: ChatState) -> Callable[[str], bool]:
    store, _ = state.stores()
    return lambda name: getattr(store.get_model(name), "identity_bearing", False) is True


def render_cost(state: ChatState, plan: GenerationPlan, cap: float | None) -> list[str]:
    ledger = state.ledger()
    rate, rate_src = _rate(state)
    lines = [
        "Cost",
        f"  Specs to render:   {len(plan.plans)}",
        f"  Per-run estimate:  ${plan.per_run_estimate_usd:.4f} "
        f"({'learned from recent runs' if plan.estimate_source == 'learned' else 'default; no history yet'})",
        f"  GPU rate:          ${rate:.2f}/hr ({rate_src})",
        f"  Session estimate:  ${plan.estimated_session_cost_usd:.4f}",
        f"  Local cumulative:  ${ledger.cumulative():.4f} inference estimates, "
        f"${ledger.pod_uptime_total():.2f} pod uptime",
    ]
    remaining = ledger.remaining()
    if remaining is not None:
        lines.append(f"  Declared budget:   ${remaining:.2f} remaining")
    if state.pod.up:
        lines.append(f"  Pod:               {state.pod.describe()}")
    return lines


def render_skips_and_advisories(state: ChatState, plan: GenerationPlan, cap: float | None) -> list[str]:
    lines: list[str] = []
    if plan.skipped:
        lines += ["", "Skipped (will not render)", *[f"  • {plan.skip_reason(sid)}" for sid in plan.skipped]]
    notes: list[str] = []
    is_identity = _is_identity(state)
    for sp in plan.plans:
        sid = sp.spec.spec_id
        notes += [f"refinement: {w}" for w in sp.warnings]
        notes += [f"LoRA strength: {w}" for w in strength_warnings(sp.spec.lora_stack, is_identity=is_identity)]
        if sp.unmapped:
            notes.append(f"{sid}: template '{sp.template.name}' has no slot for: {', '.join(sp.unmapped)}. "
                         "These will NOT affect the render.")
        if sp.neutralized_loras:
            notes.append(f"{sid}: switched off template-baked LoRA(s) the spec did not ask for: "
                         f"{', '.join(sp.neutralized_loras)}")
    if cap is not None and plan.estimated_session_cost_usd > cap:
        notes.append("estimate exceeds the cost cap: the run will stop early.")
    if notes:
        lines += ["", "Advisories", *[f"  • {n}" for n in notes]]
    return lines


def render_endpoint(state: ChatState, endpoint: str | None) -> list[str]:
    if state.dry_run:
        return ["Endpoint", "  dry-run: endpoint not checked"]
    pod = state.pod
    lines = ["Endpoint", "  ComfyUI answered /system_stats just now."]
    if not pod.rendered:
        lines += ['  First render on this pod: expect "loading models" for about 8 min',
                  "  before the first image. That is not a hang."]
    if pod.up and endpoint == pod.endpoint:
        lines.append(f"  Registry: synced against this pod at {pod.synced_at}." if pod.synced
                     else "  Registry: NOT synced against this pod. Run model_sync first.")
    return lines


def render_generate_panel(state: ChatState, path: Path, plan: GenerationPlan, attempt: AttemptPlan, aid: str,
                          endpoint: str | None) -> str:
    lines = [f"Render {len(plan.plans)} spec(s) from {path}", f"on {endpoint or 'the pod (no endpoint yet)'}", ""]
    lines += render_attempt(attempt, aid) + [""]
    lines += render_cost(state, plan, attempt.session_cost_cap_usd) + [""]
    lines += render_endpoint(state, endpoint)
    lines += render_skips_and_advisories(state, plan, attempt.session_cost_cap_usd)
    return "\n".join(lines)


# ── tools ────────────────────────────────────────────────────────────────────


def make_generation_tools(state: ChatState) -> list[ToolSpec]:
    note = project_note(state)

    async def plan_tool(a: PlanArgs) -> ToolResult:
        try:
            path, plan = await build_plan(state, a)
        except (ValueError, OSError) as e:
            return fail(str(e))
        lines = [f"Plan for {path} (nothing is spent):", "", *render_cost(state, plan, None),
                 *render_skips_and_advisories(state, plan, None)]
        if not plan.plans:
            lines.insert(1, "Nothing to render.")
        return ok("\n".join(lines), data={
            "specs": [sp.spec.spec_id for sp in plan.plans], "skipped": list(plan.skipped),
            "estimated_session_cost_usd": plan.estimated_session_cost_usd,
            "per_run_estimate_usd": plan.per_run_estimate_usd,
        })

    # generate ----------------------------------------------------------------

    async def prepared(a: GenerateArgs) -> dict[str, Any]:
        """Plan once per call: the panel and the run that follows it use the same plan and seeds."""
        key = _key(a)
        hit = state.shown.get("generate")
        if hit and hit["key"] == key:
            return hit
        assert a.attempt_plan is not None
        path, plan = await build_plan(state, a)
        hit = {"key": key, "path": path, "plan": plan, "endpoint": resolve_endpoint(state, a.endpoint),
               "attempt_id": attempt_id(a.project or state.project, a.attempt_plan)}
        state.shown["generate"] = hit
        return hit

    async def generate_precheck(a: GenerateArgs) -> str | None:
        if a.attempt_plan is None:
            return REFUSAL.format(tool="generate")
        state.shown.pop("generate", None)
        try:
            p = await prepared(a)
        except (ValueError, OSError) as e:
            return str(e)
        plan: GenerationPlan = p["plan"]
        if not plan.plans:
            return "Nothing to render. " + " ".join(plan.skip_reason(sid) for sid in plan.skipped)
        if state.dry_run:
            return None
        problem = await endpoint_problem(state, p["endpoint"])
        if problem:
            record_finding(state, "generate", problem)
        return problem

    async def generate_preview(a: GenerateArgs) -> str:
        p = await prepared(a)
        assert a.attempt_plan is not None
        return render_generate_panel(state, p["path"], p["plan"], a.attempt_plan, p["attempt_id"], p["endpoint"])

    def generate_estimate(a: GenerateArgs) -> float:
        hit = state.shown.get("generate")
        return hit["plan"].estimated_session_cost_usd if hit and hit["key"] == _key(a) else 0.0

    async def generate_tool(a: GenerateArgs) -> ToolResult:
        if a.attempt_plan is None:
            return fail(REFUSAL.format(tool="generate"))
        try:
            p = await prepared(a)
        except (ValueError, OSError) as e:
            return fail(str(e))
        state.shown.pop("generate", None)
        plan, endpoint, aid = p["plan"], p["endpoint"], p["attempt_id"]
        problem = await endpoint_problem(state, endpoint)        # the director may have sat at the prompt
        if problem:
            record_finding(state, "generate", problem)
            return fail(problem, data={"layer": "platform"})
        assert endpoint is not None
        pod = state.pod
        tracked = pod.up and endpoint == pod.endpoint
        client = state.comfy(endpoint)
        store, _ = state.stores()
        rate, _ = _rate(state)
        pod.in_flight = True
        try:
            result = await spend_generation(
                plan, endpoint=endpoint, gpu_rate=rate, max_session_cost=a.attempt_plan.session_cost_cap_usd,
                store=store, client=client, ledger=state.ledger(),
                poll_timeout=DEFAULT_POLL_TIMEOUT_SEC if pod.rendered else COLD_LOAD_POLL_TIMEOUT_SEC,
                on_wait=loading_notifier(state, client, cold=not pod.rendered),
            )
        finally:
            pod.in_flight = False

        ids = [r.generation_id for r in result.results]
        if ids:
            pod.rendered = True
            pod.generation_ids += ids
            pod.output_paths += [r.asset_path for r in result.results if r.asset_path]
            pod.unexported += len(ids)
        pod.drain_pending = bool(result.drained and tracked)
        save_attempt(state, aid, a.attempt_plan, tool="generate", generation_ids=ids, status=result.status)

        resolver = await resolver_for(state, a.project)
        total = len(plan.plans)
        lines = [f"{result.status}: rendered {len(ids)} of {total}. Session inference estimate "
                 f"${result.session_cost_usd:.4f}. Attempt {aid}."]
        lines += [f"  {resolver.display(r.generation_id)}  spec {r.spec_id}  {r.asset_path}"
                  + ("  [identity-bearing]" if r.identity_bearing else "") for r in result.results]
        if result.status == "partial":
            lines.append(f"Stopped at the cost cap (${a.attempt_plan.session_cost_cap_usd:.2f}) after {len(ids)} of {total}.")
        lines += [f"  • {reason}" for reason in result.skip_reasons]
        data: dict[str, Any] = {
            "generation_ids": ids, "attempt_id": aid, "status": result.status, "drained": result.drained,
            "inference_cost_usd": result.session_cost_usd,
            # A tracked pod is charged by uptime at pod_down; charging the estimate too would count twice.
            "cost_usd": 0.0 if tracked else result.session_cost_usd,
        }
        if result.error:
            finding = PLATFORM.format(
                endpoint=endpoint, cause="it stopped answering during the run",
                fix="A job already submitted keeps running on the pod. Fix: pod_tunnel, then generate the remaining specs.",
            ).replace("Nothing was submitted and no GPU time was spent by this call. ", "")
            record_finding(state, "generate", finding)
            return ToolResult(text="\n".join([*lines, finding]), data={**data, "layer": "platform"},
                              artifacts=[r.asset_path for r in result.results if r.asset_path], is_error=True)
        if pod.drain_pending:
            lines.append("Batch drained. Export artifacts and delete the pod before review.")
        return ok("\n".join(lines), data=data, artifacts=[r.asset_path for r in result.results if r.asset_path])

    # quick_generate ----------------------------------------------------------

    def quick_estimate(a: QuickArgs) -> float:
        return DEFAULT_PER_RUN_MINUTES / 60.0 * _rate(state)[0]

    async def quick_precheck(a: QuickArgs) -> str | None:
        if a.attempt_plan is None:
            return REFUSAL.format(tool="quick_generate")
        try:
            [parse_lora(tok) for tok in a.loras]
        except ValueError as e:
            return str(e)
        if state.dry_run:
            return None
        problem = await endpoint_problem(state, resolve_endpoint(state, a.endpoint))
        if problem:
            record_finding(state, "quick_generate", problem)
        return problem

    async def quick_preview(a: QuickArgs) -> str:
        assert a.attempt_plan is not None
        endpoint = resolve_endpoint(state, a.endpoint)
        rate, rate_src = _rate(state)
        settings = {k: v for k, v in (("seed", a.seed), ("width", a.width), ("height", a.height), ("steps", a.steps),
                                      ("cfg", a.cfg), ("sampler", a.sampler), ("scheduler", a.scheduler)) if v is not None}
        lines = [
            f"Render 1 still with template {a.template_name or DEFAULT_QUICK_IMAGE_TEMPLATE}",
            f"on {endpoint or 'the pod (no endpoint yet)'}",
            "No batch file, no canon, and no generation record in memory. The image, its submitted graph",
            "and its provenance file are saved locally.",
            "",
            f"  Prompt:    {a.prompt[:300]}",
            f"  Settings:  {', '.join(f'{k}={v}' for k, v in settings.items()) or 'template defaults, random seed'}",
        ]
        if a.loras:
            lines.append(f"  LoRAs:     {', '.join(a.loras)}")
        lines += ["", *render_attempt(a.attempt_plan, attempt_id("adhoc", a.attempt_plan)), "",
                  "Cost", f"  Estimate:  ${quick_estimate(a):.4f} at ${rate:.2f}/hr ({rate_src}); a cold model load costs more",
                  "", *render_endpoint(state, endpoint)]
        warns = strength_warnings([parse_lora(t) for t in a.loras], is_identity=_is_identity(state))
        if warns:
            lines += ["", "Advisories", *[f"  • LoRA strength: {w}" for w in warns]]
        return "\n".join(lines)

    async def quick_tool(a: QuickArgs) -> ToolResult:
        if a.attempt_plan is None:
            return fail(REFUSAL.format(tool="quick_generate"))
        endpoint = resolve_endpoint(state, a.endpoint)
        problem = await endpoint_problem(state, endpoint)
        if problem:
            record_finding(state, "quick_generate", problem)
            return fail(problem, data={"layer": "platform"})
        assert endpoint is not None
        pod = state.pod
        tracked = pod.up and endpoint == pod.endpoint
        client = state.comfy(endpoint)
        store, _ = state.stores()
        rate, _ = _rate(state)
        settings = {k: v for k, v in (("steps", a.steps), ("cfg", a.cfg), ("sampler", a.sampler),
                                      ("scheduler", a.scheduler)) if v is not None}
        pod.in_flight = True
        try:
            r = await quick_generate(
                a.prompt, endpoint=endpoint, template_name=a.template_name, negative_prompt=a.negative_prompt,
                seed=a.seed, width=a.width, height=a.height, settings=settings,
                lora_stack=[parse_lora(t) for t in a.loras], gpu_rate=rate, store=store, client=client,
                poll_timeout=DEFAULT_POLL_TIMEOUT_SEC if pod.rendered else COLD_LOAD_POLL_TIMEOUT_SEC,
                on_wait=loading_notifier(state, client, cold=not pod.rendered),
            )
        except (QuickTemplateNotFound, QuickSourceError, QuickSeedUnmapped, QuickLoraUnsafe, QuickInvalidSpec,
                ValueError) as e:
            return fail(str(e))
        except ComfyUIError as e:
            finding = await endpoint_problem(state, endpoint)
            if finding is None:
                return fail(f"ComfyUI rejected the request: {e}")
            finding = finding.replace("Nothing was submitted and no GPU time was spent by this call. ", "")
            record_finding(state, "quick_generate", finding)
            return fail(finding, data={"layer": "platform"})
        except RuntimeError as e:
            return fail(str(e))
        finally:
            pod.in_flight = False
        pod.rendered = True
        pod.output_paths.append(str(r.asset_path))
        pod.unexported += 1
        aid = attempt_id("adhoc", a.attempt_plan)
        save_attempt(state, aid, a.attempt_plan, tool="quick_generate", generation_ids=[],
                     outputs=[str(r.asset_path)], status="completed")
        lines = [f"Saved {r.asset_path}", f"Template {r.template_name}, seed {r.seed}, {r.elapsed_sec:.1f}s "
                 f"(about ${r.estimated_cost_usd:.4f}). Attempt {aid}. Not recorded to memory."]
        if r.unmapped:
            lines.append(f"Template '{r.template_name}' has no slot for: {', '.join(r.unmapped)}. "
                         "These did NOT affect the render.")
        return ok("\n".join(lines), artifacts=[str(r.asset_path)], data={
            "asset_path": str(r.asset_path), "seed": r.seed, "template": r.template_name, "attempt_id": aid,
            "elapsed_sec": r.elapsed_sec, "inference_cost_usd": r.estimated_cost_usd,
            "cost_usd": 0.0 if tracked else r.estimated_cost_usd,
        })

    # gpu_ledger --------------------------------------------------------------

    async def ledger_tool(a: NoArgs) -> ToolResult:
        ledger = state.ledger()
        remaining = ledger.remaining()
        pods = ledger.entries("pod_uptime")
        lines = [
            f"GPU ledger ({ledger.path})",
            f"  Inference estimates, cumulative:  ${ledger.cumulative():.4f}  (per-run and session estimates)",
            f"  Pod uptime, closed pods:          ${ledger.pod_uptime_total():.2f}  (create to delete; the billed axis)",
            "  These are kept apart: inference time is inside uptime, so they are not added together.",
            "  Declared budget:                  " + ("none" if remaining is None else f"${remaining:.2f} remaining"),
        ]
        if state.pod.up:
            lines.append(f"  Open now:                         {state.pod.describe()}")
        for row in pods[-5:]:
            if row.get("ended_at") is None:
                continue
            marks = [m for m, on in (("start not observed", row.get("start_observed") is False),
                                     ("end not observed", row.get("end_observed") is False)) if on]
            lines.append(f"    {row['started_at'][:16]}  {row['pod_id']}  {row['seconds'] / 60:.0f} min at "
                         f"${row['rate_usd_per_hr']:.2f}/hr = ${row['cost_usd']:.2f}"
                         + (f"  ({'; '.join(marks)})" if marks else ""))
        return ok("\n".join(lines), data={
            "inference_cumulative_usd": ledger.cumulative(), "pod_uptime_usd": ledger.pod_uptime_total(),
            "declared_budget_remaining_usd": remaining, "pod_entries": len(pods),
        })

    G = EffectClass.GPU_SPEND
    return [
        ToolSpec(name="plan_generation", effect=EffectClass.READ, input_model=PlanArgs, handler=plan_tool,
                 description="Free. Resolve the batch's specs to concrete graphs and show the cost estimate, what "
                             "would be skipped and why, and the advisories. Spends nothing. " + note),
        ToolSpec(name="generate", effect=G, input_model=GenerateArgs, handler=generate_tool,
                 precheck=generate_precheck, preview=generate_preview, estimate_cost=generate_estimate,
                 preview_is_complete=True,
                 description="SPENDS GPU. Render specs from the batch on the pod. Refused without an attempt_plan "
                             "(question, baseline, hypothesis, changed variable, controls, acceptance gate, stop rule, "
                             "cost cap); the cap is a hard ceiling. A spec sourced from a generation without a positive "
                             "reaction is skipped. The director confirms. " + note),
        ToolSpec(name="quick_generate", effect=G, input_model=QuickArgs, handler=quick_tool,
                 precheck=quick_precheck, preview=quick_preview, estimate_cost=quick_estimate,
                 preview_is_complete=True,
                 description="SPENDS GPU. One still straight from a prompt: no batch file, no canon, no memory record. "
                             "Needs an attempt_plan like any paid run. The director confirms."),
        ToolSpec(name="gpu_ledger", effect=EffectClass.READ, input_model=NoArgs, handler=ledger_tool,
                 description="Show GPU spend: inference estimates, pod uptime (its own entries), and any declared budget."),
    ]
