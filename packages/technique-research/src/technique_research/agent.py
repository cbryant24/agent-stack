"""technique-research agent entry point.

The Mode A turn: ground the reference → identify prioritized technique domains →
check existing knowledge per domain → gate (interactive prune) → delegate gaps to
tutorial-research → curate findings → write the TechniqueReport, the
`technique_research_outputs` points, and the standard run report.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable

from anthropic import AsyncAnthropic

from agent_runtime import (
    BudgetEnvelope,
    BudgetExhaustedError,
    BudgetTracker,
    MemoryStore,
    UserKnowledgeStore,
    delegate,
    get_config,
    get_memory_store,
    list_agents,
    notify_run_complete,
    register_agent,
    render_run_report,
)
from tutorial_research.retrieval import retrieve_chunks

from technique_research.chains import (
    assess_reference,
    curate_findings,
    identify_techniques,
)
from technique_research.constants import (
    AGENT_NAME,
    CURATION_MATERIAL_LIMIT,
    DEFAULT_BUDGET,
    DELEGATE_TARGET_TUTORIAL_RESEARCH,
    DELEGATION_CHILD,
    TUTORIAL_RESEARCH_COLLECTION,
)
from technique_research.grounding import fetch_url_context, tavily_reference_search
from technique_research.models import (
    CheckOutcome,
    GapOutcome,
    GroundedReference,
    IdentificationInput,
    TechniqueDomain,
    TechniqueFinding,
    TechniqueReport,
    TechniqueResult,
)
from technique_research.retrieval import check_domain, read_editing_toolset
from technique_research.store import TechniqueResearchStore

logger = logging.getLogger(__name__)

# approval(domains, check_outcomes) -> set of domain names approved for delegation.
ApprovalCallback = Callable[[list[TechniqueDomain], list[CheckOutcome]], set[str]]


# ── Delegate-handler bootstrap (copied shape from visual_generation/research.py) ─


async def _tutorial_research_handler(
    request: dict[str, Any], budget: BudgetEnvelope
) -> dict[str, Any]:
    from tutorial_research import research as tutorial_research

    result = await tutorial_research(
        request["request"],
        budget=budget,
        request_type=request.get("request_type"),
        synthesize=request.get("synthesize", False),
    )
    return {
        "status": result.status,
        "items_processed": result.items_processed,
        "synthesis": result.synthesis,
        "run_id": result.run_id,
    }


def register_delegate_handlers() -> None:
    """Idempotent bootstrap — register the tutorial-research delegate handler."""
    if DELEGATE_TARGET_TUTORIAL_RESEARCH not in list_agents():
        register_agent(DELEGATE_TARGET_TUTORIAL_RESEARCH, _tutorial_research_handler)


# ── Budget helper ─────────────────────────────────────────────────────────────


def _cap(parent: float | int | None, child: float | int) -> float | int:
    return child if parent is None else min(parent, child)


def _delegation_budget(effective: BudgetEnvelope) -> BudgetEnvelope:
    """Per-delegation budget passed to delegate(); delegate() derives a child from
    it (→ tutorial-research at depth 0), so max_depth=1 keeps the depth check
    satisfied while permitting exactly the one hop."""
    return BudgetEnvelope(
        session_id=effective.session_id,
        parent_run_id=effective.session_id,
        max_items=_cap(effective.max_items, DELEGATION_CHILD["max_items"]),
        max_depth=1,
        max_cost_usd=_cap(effective.max_cost_usd, DELEGATION_CHILD["max_cost_usd"]),
        max_wall_time_sec=_cap(effective.max_wall_time_sec, DELEGATION_CHILD["max_wall_time_sec"]),
        mode=effective.mode,
    )


# ── Material gathering for curation ───────────────────────────────────────────


async def _gather_material(
    domain: TechniqueDomain,
    store: TechniqueResearchStore,
    memory_store: MemoryStore,
) -> str:
    """Format the material a domain will be curated from: tutorial_research chunks
    (which a just-completed delegation has refreshed) plus own prior findings."""
    chunks, own = await asyncio.gather(
        retrieve_chunks(
            TUTORIAL_RESEARCH_COLLECTION, domain.search_query,
            limit=CURATION_MATERIAL_LIMIT, store=memory_store,
        ),
        store.search_findings(domain.search_query, limit=3),
    )
    parts: list[str] = []
    if chunks:
        parts.append("From tutorials / knowledge:")
        for c in chunks:
            parts.append(f"- [{c.score:.2f}] {c.source_title or c.source_id}: {c.content[:300]}")
    if own:
        parts.append("From prior findings:")
        for score, f in own:
            parts.append(f"- {f.technique}: {f.description[:200]}")
    return "\n".join(parts)


# ── Main entry point ──────────────────────────────────────────────────────────


async def identify(
    inp: IdentificationInput,
    *,
    budget: BudgetEnvelope | None = None,
    approval: ApprovalCallback | None = None,
    plan_only: bool = False,
    output_path: Path | None = None,
) -> TechniqueResult:
    register_delegate_handlers()
    config = get_config()
    effective_budget = budget or DEFAULT_BUDGET
    client = AsyncAnthropic(api_key=config.anthropic_api_key)

    memory_store = get_memory_store()
    store = TechniqueResearchStore(memory_store)
    uks = UserKnowledgeStore(memory_store)
    await store.ensure_collection()

    status = "completed"
    tracker_ref: BudgetTracker | None = None
    run_id = ""
    domains: list[TechniqueDomain] = []
    outcomes: list[CheckOutcome] = []
    findings: list[TechniqueFinding] = []
    gaps: list[GapOutcome] = []
    finding_ids: list[str] = []
    scope = inp.scope or "editing"
    grounded_summary = ""
    preview_report: TechniqueReport | None = None

    try:
        async with BudgetTracker(effective_budget, AGENT_NAME) as tracker:
            tracker_ref = tracker
            run_id = tracker.run_id

            # Run-level toolset read — the ONLY source of toolset facts.
            toolset_ctx = await read_editing_toolset(inp.goal, uks)

            # Stage 1: ground the reference (deterministic context + conditional Tavily).
            url_metadata = await fetch_url_context(inp.url) if inp.url else None
            exemplars: list[str] = []
            ref_excerpt = _read_ref(inp.ref_report)
            if ref_excerpt:
                exemplars.append(f"[prior report --ref]: {ref_excerpt}")

            assessment = await assess_reference(inp, url_metadata, client)
            if assessment["needs_grounding"] and assessment.get("tavily_query"):
                exemplars += await tavily_reference_search(assessment["tavily_query"])
            grounded = GroundedReference(
                summary=assessment.get("preliminary_summary", ""),
                exemplars=exemplars,
                url_metadata=url_metadata,
            )

            # Prior findings as identification context.
            prior = await store.search_findings(inp.goal, limit=5)
            prior_summary = "\n".join(f"- {f.technique}: {f.description[:150]}" for _, f in prior)

            # Stage 2: identification.
            tracker.check_budget()
            domains, grounded_summary, scope = await identify_techniques(
                inp, grounded, toolset_ctx, prior_summary, client
            )

            # Stage 3: check each domain.
            outcomes = await asyncio.gather(
                *(check_domain(d, store, memory_store, uks) for d in domains)
            )
            outcomes = list(outcomes)
            decision_by_name = {o.domain_name: o.decision for o in outcomes}

            if plan_only:
                # Preview: no delegation, no writes, no curation call. Report is
                # assembled and finalized after the tracker context exits cleanly.
                preview_report = _preview_report(
                    inp.goal, scope, grounded_summary, domains, outcomes
                )
            else:
                # The gate: which delegate-candidate domains to actually gather.
                delegate_candidates = [
                    d for d in domains if decision_by_name.get(d.name) == "delegate"
                ]
                if approval is not None:
                    approved = approval(domains, outcomes)
                else:
                    approved = {d.name for d in delegate_candidates}  # -y: auto-approve all

                # Stage 4a: delegate approved gaps (max_items caps DELEGATIONS, not findings).
                deleg_refs: list[str] = []
                try:
                    for d in delegate_candidates:
                        if d.name not in approved:
                            gaps.append(GapOutcome(domain_name=d.name, delegated=False, status="declined"))
                            continue
                        tracker.check_budget()  # before delegating — the tutorial-research pattern
                        result = await delegate(
                            DELEGATE_TARGET_TUTORIAL_RESEARCH,
                            {"request": d.search_query, "request_type": "research", "synthesize": True},
                            _delegation_budget(effective_budget),
                            parent_tracker=tracker,
                        )
                        tracker.add_item_processed()  # one item == one technique gathered
                        child_run = ""
                        items = 0
                        if result.result:
                            child_run = result.result.get("run_id", "")
                            items = result.result.get("items_processed", 0)
                        if child_run:
                            deleg_refs.append(f"tutorial-research run {child_run}")
                        gaps.append(GapOutcome(
                            domain_name=d.name, delegated=True,
                            status=result.status, run_id=child_run, items_processed=items,
                        ))
                except BudgetExhaustedError:
                    status = "partial"

                # Local-resolved domains are curated from existing knowledge.
                for d in domains:
                    if decision_by_name.get(d.name) == "local":
                        gaps.append(GapOutcome(domain_name=d.name, delegated=False, status="local"))

                # Stage 4b: curate findings over all domains and their resolved material.
                material_by_domain = {
                    d.name: await _gather_material(d, store, memory_store) for d in domains
                }
                raw = await curate_findings(
                    inp.goal, scope, domains, material_by_domain, toolset_ctx, client
                )
                findings = _build_findings(raw, inp.goal, scope, deleg_refs)

                # Stage 4c: write findings (NOT item-counted — max_items is the delegation cap).
                finding_ids = await store.upsert_findings(findings, run_id)

    except BudgetExhaustedError:
        status = "partial"

    if preview_report is not None:
        report = preview_report
    else:
        report = TechniqueReport(
            goal=inp.goal, scope=scope, grounded_reference_summary=grounded_summary,
            techniques=findings, gaps=gaps,
        )
    report_path = _write_report(report, output_path, config)
    return _finalize(
        report, report_path, finding_ids, domains, outcomes, run_id, status, tracker_ref,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _read_ref(ref: Path | None) -> str:
    if ref is None:
        return ""
    try:
        return Path(ref).read_text(encoding="utf-8")[:1500]
    except Exception as exc:
        logger.warning("Could not read --ref report %s: %s", ref, exc)
        return ""


def _build_findings(
    raw: list[dict[str, Any]], goal: str, scope: str, deleg_refs: list[str]
) -> list[TechniqueFinding]:
    findings: list[TechniqueFinding] = []
    for r in raw:
        technique = (r.get("technique") or "").strip()
        if not technique:
            continue
        findings.append(TechniqueFinding(
            technique=technique,
            description=r.get("description", ""),
            why_it_matters=r.get("why_it_matters", ""),
            application_notes=r.get("application_notes", ""),
            toolset_fit=r.get("toolset_fit", ""),
            upgrade_flag=r.get("upgrade_flag") or None,
            source_refs=list(deleg_refs),
            goal_context=goal,
            domain_context=technique,
            scope=scope if scope in ("editing", "generation", "both") else "editing",
        ))
    return findings


def _preview_report(
    goal: str, scope: str, summary: str,
    domains: list[TechniqueDomain], outcomes: list[CheckOutcome],
) -> TechniqueReport:
    decision_by_name = {o.domain_name: o.decision for o in outcomes}
    techniques = [
        TechniqueFinding(
            technique=d.name, description=d.why_it_matters, why_it_matters=d.why_it_matters,
            goal_context=goal, domain_context=d.name, scope=d.scope,
        )
        for d in domains
    ]
    gaps = [
        GapOutcome(domain_name=d.name, delegated=False,
                   status=("would delegate" if decision_by_name.get(d.name) == "delegate" else "local"))
        for d in domains
    ]
    return TechniqueReport(
        goal=goal, scope=scope, grounded_reference_summary=summary,
        techniques=techniques, gaps=gaps, preview=True,
    )


def _write_report(report: TechniqueReport, output_path: Path | None, config: Any) -> Path:
    if output_path is not None:
        path = Path(output_path)
        # A directory target means "write the default filename into it" — so an
        # existing-dir path is never an IsADirectoryError at the final write.
        if path.is_dir():
            path = path / report.default_filename()
    else:
        path = config.agent_data_dir / "technique-reports" / report.default_filename()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.to_markdown(), encoding="utf-8")
    return path


def _finalize(
    report: TechniqueReport,
    report_path: Path,
    finding_ids: list[str],
    domains: list[TechniqueDomain],
    outcomes: list[CheckOutcome],
    run_id: str,
    status: str,
    tracker_ref: BudgetTracker | None,
) -> TechniqueResult:
    cost_usd = items = wall = 0.0
    if tracker_ref is not None:
        snap = tracker_ref._consumption
        cost_usd, items, wall = snap.cost_usd, snap.items_processed, snap.wall_time_sec

    report_run_path: Path | None = None
    if run_id:
        try:
            report_run_path = render_run_report(run_id, AGENT_NAME)
        except FileNotFoundError:
            pass
        notify_run_complete(AGENT_NAME, run_id, status, cost_usd)

    return TechniqueResult(
        report=report, report_path=report_path, report_run_path=report_run_path,
        finding_ids=finding_ids, domains=domains, check_outcomes=outcomes,
        run_id=run_id, status=status, cost_usd=cost_usd,
        items_processed=int(items), wall_time_sec=wall,
    )


def identify_sync(inp: IdentificationInput, **kwargs: Any) -> TechniqueResult:
    return asyncio.run(identify(inp, **kwargs))


# ── recall ────────────────────────────────────────────────────────────────────


async def recall(query: str, *, limit: int = 8) -> list[tuple[float, TechniqueFinding]]:
    store = TechniqueResearchStore(get_memory_store())
    return await store.search_findings(query, limit=limit)


def recall_sync(query: str, *, limit: int = 8) -> list[tuple[float, TechniqueFinding]]:
    return asyncio.run(recall(query, limit=limit))
