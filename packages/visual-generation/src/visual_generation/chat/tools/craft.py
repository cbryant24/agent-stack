"""Tools that spend LLM money (a craft or tutor call) but never GPU and never write memory.

`draft`, `redraft` and `batch_build` append to the project's batch file: a director-owned
working artifact (a file write, not a memory write); the result names the path. Library
functions are called in-process, async, with the session's stores.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from agent_runtime import BudgetEnvelope
from agent_shell.tools.registry import EffectClass, ToolResult, ToolSpec
from pydantic import BaseModel, Field

from visual_generation.chat.state import ChatState
from visual_generation.chat.tools._common import fail, ok, project_note, resolve_ref
from visual_generation.discovery import discover_scenes
from visual_generation.draft import (
    RefinementSourceError,
    build_refinement_source,
    draft as _draft,
    redraft as _redraft,
)
from visual_generation.evaluation import strike_status
from visual_generation.explain import explain as _explain
from visual_generation.explain import render_explain
from visual_generation.models import DraftResult, VisualSource

# Per-call hard caps (the session's tool budget still charges the real cost).
DRAFT_CAP = BudgetEnvelope(max_items=1, max_depth=1, max_cost_usd=0.25, max_wall_time_sec=300)
EXPLAIN_CAP = BudgetEnvelope(max_items=1, max_depth=1, max_cost_usd=0.15, max_wall_time_sec=300)
BATCH_TOTAL_CAP_USD = 2.00
# What the gate assumes before a call (the executor charges the actual cost afterwards).
DRAFT_ESTIMATE_USD = 0.05
EXPLAIN_ESTIMATE_USD = 0.03

Level = Literal["full", "concise", "quiet"]


class ExplainArgs(BaseModel):
    concept: str = Field(description="The concept to explain, grounded in your own lessons.")
    level: Level | None = Field(default=None, description="Verbosity of the generic gloss.")


class DraftArgs(BaseModel):
    intent: str | None = Field(default=None, description="What the image should show (a key point).")
    points: list[str] = Field(default_factory=list, description="Further key points.")
    scene: str | None = Field(default=None, description="Narrow to one scene heading in directed.md/script.md.")
    template: str | None = Field(default=None, description="Workflow template name (default: top retrieved).")
    from_generation: str | None = Field(
        default=None, description="Refine a prior generation (label like 'attempt-07', or id). "
                                  "Exclusive with image_path.")
    image_path: str | None = Field(default=None, description="Refine from an image on disk. Exclusive with from_generation.")
    mask: str | None = Field(default=None, description="Inpaint mask PNG (white = area to change). Needs a source.")
    denoise: float | None = Field(default=None, ge=0.0, le=1.0, description="Refinement denoise. Only applies with a source.")
    canon: list[str] = Field(default_factory=list, description="Force these canon subjects into the cast.")
    project: str | None = None


class RedraftArgs(BaseModel):
    generation: str = Field(description="The attempt to revise: label like 'attempt-07', or id.")
    change: str = Field(description="The one change to apply to its prompt.")
    canon: list[str] = Field(default_factory=list)
    project: str | None = None


class BatchBuildArgs(BaseModel):
    from_generation: str | None = Field(default=None, description="Anchor every scene to this generation (img2img).")
    image_path: str | None = Field(default=None, description="Anchor every scene to this image.")
    denoise: float | None = Field(default=None, ge=0.0, le=1.0)
    template: str | None = None
    project: str | None = None


def _exists(path: str | None) -> str | None:
    if path and not Path(path).expanduser().is_file():
        return path
    return None


def summarize_draft(result: DraftResult, *, denoise: float | None, project: str | None) -> tuple[str, list[str]]:
    """(text, warnings). Always names the template and modality (KI-8)."""
    spec = result.spec
    warnings = list(result.revise_warnings)
    if denoise is not None and spec.source is None:
        warnings.append(
            "denoise was given but there is no source image, so it has no effect on a text-to-image draft"
        )
    if result.template_modality in ("img2img", "inpaint") and spec.source is None:
        warnings.append(
            f"the template '{result.template_name}' is {result.template_modality} but this draft has no "
            "source; it will not render as text-to-image. Name a text2img template or give a source."
        )
    warnings += [f"inherited but not applied: {w}" for w in result.inert_inheritance]
    warnings += [f"required model not in registry: {m}" for m in result.missing_models]
    warnings += [f"canon subject named in the scene but absent from the prompt: {c}" for c in result.canon_absent]

    modality = f" [{result.template_modality}]" if result.template_modality else ""
    lines = [
        f"Spec {spec.spec_id} ({result.status}), cost ${result.cost_usd:.4f}",
        f"Template: {result.template_name or '(none: settings unconstrained)'}{modality}",
        f"Model: {spec.model or '(none chosen)'}" + ("  [identity-bearing]" if spec.identity_bearing else ""),
    ]
    if spec.source is not None:
        origin = spec.source.from_generation or spec.source.image_path
        lines.append(f"Refining: {origin} [{'inpaint' if spec.source.mask else 'img2img'}], "
                     f"denoise {spec.settings.get('denoise', '0.5 default')}")
    lines.append(f"Prompt: {spec.prompt[:400]}")
    if spec.lora_stack:
        lines.append("LoRAs: " + ", ".join(f"{lr.name}@{lr.strength}" for lr in spec.lora_stack))
    if result.canon_applied:
        lines.append("Canon applied: " + "; ".join(result.canon_applied))
    if result.overall_reasoning:
        lines.append(f"Rationale: {result.overall_reasoning[:300]}")
    if warnings:
        lines.append("Warnings:")
        lines.extend(f"  - {w}" for w in warnings)
    if result.batch_path:
        lines.append(f"Appended to {result.batch_path}")
    return "\n".join(lines), warnings


def _draft_data(result: DraftResult, warnings: list[str]) -> dict[str, object]:
    return {
        "spec_id": result.spec.spec_id, "status": result.status, "cost_usd": result.cost_usd,
        "template": result.template_name, "modality": result.template_modality,
        "model": result.spec.model, "batch_path": str(result.batch_path) if result.batch_path else None,
        "warnings": warnings,
    }


def make_craft_tools(state: ChatState) -> list[ToolSpec]:
    note = project_note(state)

    async def source_for(
        from_ref: str | None, image_path: str | None, mask: str | None, template: str | None
    ) -> tuple[VisualSource | None, str | None] | ToolResult:
        gen_id = None
        if from_ref:
            gen_id, why = await resolve_ref(state, from_ref)
            if gen_id is None:
                return fail(f"Could not resolve {from_ref!r}: {why}", data={"open_questions": [why]})
        try:
            source, template_name = build_refinement_source(gen_id, image_path, mask, template)
        except RefinementSourceError as e:
            return fail(str(e))
        for p in (image_path, mask):
            if _exists(p):
                return fail(f"No such file: {p}")
        return source, template_name

    async def explain_tool(a: ExplainArgs) -> ToolResult:
        store, ms = state.stores()
        result = await _explain(a.concept, level=a.level, budget=EXPLAIN_CAP, store=store, memory_store=ms)
        return ok(render_explain(result), data={"cost_usd": result.cost_usd, "status": result.status})

    async def draft_tool(a: DraftArgs) -> ToolResult:
        if not (a.intent or a.points or a.scene):
            return fail("Give an intent, key points, or a scene to draft from.")
        try:
            path = state.batch_path(a.project)
        except ValueError as e:
            return fail(str(e))
        built = await source_for(a.from_generation, a.image_path, a.mask, a.template)
        if isinstance(built, ToolResult):
            return built
        source, template = built
        store, ms = state.stores()
        result = await _draft(
            a.intent, points=a.points or None, scene=a.scene, batch_path=path,
            projects_dir=state.projects_dir, template_name=template,
            project=a.project or state.project, source=source, denoise=a.denoise,
            force_canon=a.canon or None, budget=DRAFT_CAP, store=store, memory_store=ms,
        )
        text, warnings = summarize_draft(result, denoise=a.denoise, project=a.project or state.project)
        if result.status == "failed":
            return fail("Draft failed (no spec produced).\n" + text, data=_draft_data(result, warnings))
        return ok(text, data=_draft_data(result, warnings), artifacts=[str(path)])

    async def redraft_tool(a: RedraftArgs) -> ToolResult:
        try:
            path = state.batch_path(a.project)
        except ValueError as e:
            return fail(str(e))
        gen_id, why = await resolve_ref(state, a.generation)
        if gen_id is None:
            return fail(f"Could not resolve {a.generation!r}: {why}", data={"open_questions": [why]})
        store, ms = state.stores()
        # Three strikes: after three failed same-class attempts, a fourth needs a written question.
        gen = await store.get_generation(gen_id)
        if gen is not None:
            strike = strike_status(await store.list_evaluations(chain_root_id=gen.chain_root_id))
            if strike.blocked:
                return fail(
                    f"{strike.count} attempts at fix class {strike.strike_class!r} have failed in this chain. "
                    "A fourth redraft needs a written architecture question first: use propose_interpretation "
                    "with `architecture_question` (the layer being blamed and a different layer that could be "
                    "at fault) and record it, or change layer (new_draft, refine_img2img, inpaint).",
                    data={"strike": strike.model_dump()},
                )
        result = await _redraft(
            gen_id, a.change, batch_path=path, project=a.project or state.project,
            force_canon=a.canon or None, budget=DRAFT_CAP, store=store, memory_store=ms,
        )
        text, warnings = summarize_draft(result, denoise=None, project=a.project or state.project)
        if result.status == "failed":
            return fail("Redraft failed (no spec produced).\n" + text, data=_draft_data(result, warnings))
        return ok(text, data=_draft_data(result, warnings), artifacts=[str(path)])

    def scenes_of(project: str | None) -> list[str]:
        slug = project or state.project
        return discover_scenes(slug, projects_dir=state.projects_dir) if slug else []

    async def batch_build_tool(a: BatchBuildArgs) -> ToolResult:
        slug = a.project or state.project
        try:
            path = state.batch_path(a.project)
        except ValueError as e:
            return fail(str(e))
        if path.exists():
            return fail(f"A batch already exists at {path}. Rebuilding is not available in chat; "
                        "draft individual scenes, or move the file yourself first.")
        scenes = scenes_of(slug)
        if not scenes:
            return fail(f"No scenes found for {slug!r}: it needs a directed.md or script.md with '##' scene headings.")
        built = await source_for(a.from_generation, a.image_path, None, a.template)
        if isinstance(built, ToolResult):
            return built
        source, template = built
        store, ms = state.stores()
        results: list[DraftResult] = []
        spent = 0.0
        for heading in scenes:
            if spent >= BATCH_TOTAL_CAP_USD:
                break
            r = await _draft(
                None, scene=heading, project=slug, projects_dir=state.projects_dir, batch_path=path,
                template_name=template, source=source, denoise=a.denoise, budget=DRAFT_CAP,
                store=store, memory_store=ms,
            )
            spent += r.cost_usd
            results.append(r)
        done = [r for r in results if r.status != "failed"]
        lines = [f"Built {len(done)} of {len(scenes)} scene spec(s) into {path} (cost ${spent:.4f})."]
        if len(results) < len(scenes):
            lines.append(f"Stopped after {len(results)}: the ${BATCH_TOTAL_CAP_USD:.2f} batch cap was reached.")
        for r in results:
            _, warns = summarize_draft(r, denoise=a.denoise, project=slug)
            mark = "FAILED" if r.status == "failed" else r.spec.spec_id
            lines.append(f"  {r.spec.heading or '(scene)'}: {mark}" + (f"  ⚠ {len(warns)} warning(s)" if warns else ""))
        return ok("\n".join(lines), artifacts=[str(path)], data={
            "cost_usd": spent, "built": len(done), "scenes": len(scenes), "batch_path": str(path),
        })

    L = EffectClass.LLM_SPEND
    return [
        ToolSpec(name="explain", effect=L, input_model=ExplainArgs, handler=explain_tool,
                 estimate_cost=lambda a: EXPLAIN_ESTIMATE_USD,
                 preview=lambda a: f"explain {a.concept!r} (LLM call, about ${EXPLAIN_ESTIMATE_USD:.2f})",
                 description="Grounded tutor explanation of a concept, always including your own lessons. "
                             "Uses Claude even when this chat runs on another provider."),
        ToolSpec(name="draft", effect=L, input_model=DraftArgs, handler=draft_tool,
                 estimate_cost=lambda a: DRAFT_ESTIMATE_USD,
                 preview=lambda a: f"draft a spec ({a.intent or a.scene or 'key points'}) and append it to the batch file",
                 description="Craft one generation spec from key points plus the project's docs and retrieved "
                             "knowledge, and append it to the project's batch file. Free of GPU cost. "
                             "The result names the template and its modality. " + note),
        ToolSpec(name="redraft", effect=L, input_model=RedraftArgs, handler=redraft_tool,
                 estimate_cost=lambda a: DRAFT_ESTIMATE_USD,
                 preview=lambda a: f"redraft {a.generation}: {a.change[:80]}",
                 description="Revise a prior generation's prompt with one change, inheriting its recipe, and "
                             "append the new spec to the batch file. " + note),
        ToolSpec(name="batch_build", effect=L, input_model=BatchBuildArgs, handler=batch_build_tool,
                 estimate_cost=lambda a: DRAFT_ESTIMATE_USD * max(len(scenes_of(a.project)), 1),
                 preview=lambda a: f"compile one spec per scene of the project into a new batch file "
                                   f"({len(scenes_of(a.project))} scene(s))",
                 description="Compile one spec per scene of the project's directed.md/script.md into a NEW "
                             "batch file (refuses if one exists). " + note),
    ]
