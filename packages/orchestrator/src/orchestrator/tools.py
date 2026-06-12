"""The orchestrator's v1 tool set.

Sub-agent tools call each agent's existing async library entry point in-process
with a derived child budget, so budget parent/child, tracing, and the shared
Qdrant client propagate naturally. Knowledge + repo-access tools serve both direct
queries and system-introspection ("what does agent X do / how is it built").
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from langchain_core.tools import tool

from agent_runtime import BudgetEnvelope
from agent_runtime.budget import get_current_tracker
from agent_runtime.tracing import record_delegation_decision

from orchestrator import constants
from orchestrator.retrieval import Domain, search_knowledge as _search_knowledge

logger = logging.getLogger(__name__)

_MAX_TOOL_OUTPUT_CHARS = 8000
_MAX_READ_FILE_CHARS = 20000
_MAX_GREP_MATCHES = 80


def _child_budget() -> BudgetEnvelope:
    """Derive a capped child budget for an in-process sub-agent delegation from the
    active per-turn envelope (the parent). Falls back to DEFAULT_BUDGET off-turn."""
    tracker = get_current_tracker()
    parent = tracker.envelope if tracker is not None else constants.DEFAULT_BUDGET

    cost = constants.SUBAGENT_COST_CAP_USD
    if parent.max_cost_usd is not None:
        cost = min(cost, parent.max_cost_usd * constants.SUBAGENT_COST_FRACTION)
    wall = constants.SUBAGENT_WALL_TIME_CAP_SEC
    if parent.max_wall_time_sec is not None:
        wall = min(wall, int(parent.max_wall_time_sec * constants.SUBAGENT_WALL_TIME_FRACTION))

    return parent.derive_child(
        max_items=constants.SUBAGENT_MAX_ITEMS,
        max_cost_usd=cost,
        max_wall_time_sec=wall,
    )


def _record_delegation(tool_name: str, collection: str, query: str, cost_usd: float) -> None:
    tracker = get_current_tracker()
    if tracker is not None:
        tracker.add_delegation(child_cost_usd=cost_usd)
    record_delegation_decision(
        trigger_type=f"tool:{tool_name}",
        collection=collection,
        query=query,
        local_max_score=0.0,
        threshold=0.0,
        decision="delegate",
    )


def _truncate(text: str, limit: int = _MAX_TOOL_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…[truncated, {len(text) - limit} more chars]"


# ── Knowledge ─────────────────────────────────────────────────────────────────


@tool
async def search_knowledge(query: str, domain: Domain) -> str:
    """Semantic search over one of the system's knowledge bases.

    domain must be one of:
      - "tutorial_research": YouTube tutorial knowledge (Suno, music theory, production).
      - "music_curation_memory": the music-curation agent's generation/taste memory.
      - "voiceover_direction_memory": the voiceover-direction agent's takes/direction-lesson memory.
      - "visual_generation_memory": the visual-generation agent's generation/technique memory.
      - "technique_research_outputs": the technique-research agent's curated per-technique findings.
      - "langgraph_mechanics": LangGraph mechanics facts in user_knowledge.
    Authoritative user_knowledge hits are boosted. Returns scored snippets.
    """
    try:
        results = await _search_knowledge(query, domain)
    except ValueError as exc:
        return str(exc)
    except Exception as exc:  # graceful degrade — never crash the loop
        logger.warning("search_knowledge failed: %s", exc)
        return f"Knowledge search failed ({exc.__class__.__name__}); no results available."
    if not results:
        return f"No results in '{domain}' for: {query}"
    lines = [f"[{r.score:.3f}] ({r.collection}) {r.label}: {r.snippet[:300]}" for r in results]
    return _truncate("\n".join(lines))


# ── Live repo access (Claude-Code style) ───────────────────────────────────────


def _resolve_in_repo(path: str) -> Path:
    root = constants.repo_root()
    candidate = (root / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    if root not in candidate.parents and candidate != root:
        raise ValueError("path escapes the repository root")
    return candidate


@tool
def read_file(path: str) -> str:
    """Read a UTF-8 text file from the agent-stack repository (relative to the repo
    root, e.g. 'packages/music-curation/src/music_curation/agent.py' or
    'docs/ai-director-agent-system.md'). Use this to inspect source and docs when
    answering questions about how an agent works or how to use it."""
    try:
        resolved = _resolve_in_repo(path)
    except ValueError as exc:
        return f"Refused: {exc}"
    if not resolved.is_file():
        return f"Not found: {path}"
    try:
        text = resolved.read_text(encoding="utf-8")
    except Exception as exc:
        return f"Could not read {path}: {exc}"
    return _truncate(text, _MAX_READ_FILE_CHARS)


@tool
def grep(pattern: str, path_glob: str | None = None) -> str:
    """Search the repository's packages/ and docs/ for a regex pattern, returning
    matching 'file:line: text' rows. Optionally restrict to a glob (e.g. '*.py').
    Use this to locate code, definitions, or docs across the system."""
    root = constants.repo_root()
    search_dirs = [str(root / "packages"), str(root / "docs")]
    cmd = ["rg", "--line-number", "--no-heading", "--color", "never"]
    if path_glob:
        cmd += ["--glob", path_glob]
    cmd += [pattern, *search_dirs]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except FileNotFoundError:
        return _python_grep(pattern, path_glob, root)
    except Exception as exc:
        return f"grep failed: {exc}"
    if proc.returncode not in (0, 1):  # 1 = no matches
        return f"grep error: {proc.stderr.strip()[:400]}"
    out_lines = [_relativize(line, root) for line in proc.stdout.splitlines() if line.strip()]
    if not out_lines:
        return f"No matches for: {pattern}"
    if len(out_lines) > _MAX_GREP_MATCHES:
        extra = len(out_lines) - _MAX_GREP_MATCHES
        out_lines = out_lines[:_MAX_GREP_MATCHES] + [f"…[{extra} more matches]"]
    return _truncate("\n".join(out_lines))


def _relativize(line: str, root: Path) -> str:
    prefix = str(root) + "/"
    return line[len(prefix):] if line.startswith(prefix) else line


def _python_grep(pattern: str, path_glob: str | None, root: Path) -> str:
    """Fallback when ripgrep is unavailable."""
    import re

    try:
        rx = re.compile(pattern)
    except re.error as exc:
        return f"Invalid regex: {exc}"
    matches: list[str] = []
    for base in ("packages", "docs"):
        for fp in (root / base).rglob(path_glob or "*"):
            if not fp.is_file():
                continue
            try:
                for i, text in enumerate(fp.read_text(encoding="utf-8").splitlines(), 1):
                    if rx.search(text):
                        matches.append(f"{fp.relative_to(root)}:{i}: {text.strip()[:200]}")
                        if len(matches) >= _MAX_GREP_MATCHES:
                            return _truncate("\n".join(matches))
            except (UnicodeDecodeError, OSError):
                continue
    return "\n".join(matches) if matches else f"No matches for: {pattern}"


# ── Sub-agent tools: tutorial-research ──────────────────────────────────────────


@tool
async def tutorial_retrieve(query: str) -> str:
    """Query the tutorial-research knowledge base WITHOUT ingesting anything
    (near-free, embedding-only). Returns relevant tutorial chunks. Prefer this over
    research_tutorials unless new material genuinely needs to be gathered."""
    from tutorial_research import research

    try:
        result = await research(query, budget=_child_budget(), request_type="retrieve", synthesize=False)
    except Exception as exc:
        logger.warning("tutorial_retrieve failed: %s", exc)
        return f"tutorial-research retrieve failed: {exc}"
    _record_delegation("tutorial_retrieve", "tutorial_research", query, result.cost_usd)
    chunks = result.retrieved[:8]
    if not chunks:
        return f"No tutorial knowledge found for: {query}"
    lines = [f"[{c.score:.3f}] {c.source_title or c.source_id}: {c.content[:280]}" for c in chunks]
    return _truncate(f"status={result.status} cost=${result.cost_usd:.4f}\n" + "\n".join(lines))


@tool
async def research_tutorials(topic: str) -> str:
    """Run the tutorial-research agent in RESEARCH mode: discover YouTube tutorials
    on a topic, ingest them into the knowledge base, and synthesize findings. This
    SPENDS budget (discovery + ingestion + synthesis) — use only when existing
    knowledge is insufficient and new material is warranted."""
    from tutorial_research import research

    try:
        result = await research(topic, budget=_child_budget(), request_type="research")
    except Exception as exc:
        logger.warning("research_tutorials failed: %s", exc)
        return f"tutorial-research run failed: {exc}"
    _record_delegation("research_tutorials", "tutorial_research", topic, result.cost_usd)
    parts = [
        f"status={result.status} cost=${result.cost_usd:.4f} ingested={len(result.ingested)}",
    ]
    if result.synthesis:
        parts.append("\nSynthesis:\n" + result.synthesis)
    return _truncate("\n".join(parts))


# ── Sub-agent tools: music-curation ─────────────────────────────────────────────


@tool
async def music_recall(query: str) -> str:
    """Recall prior music-curation work WITHOUT generating new prompts (dry-run:
    retrieves taste/generation memory and surfaces similar prior generations, no
    LLM generation cost). Use to look up what's been made or learned before."""
    from music_curation import curate

    try:
        result = await curate(query, budget=_child_budget(), dry_run=True, skip_question=True)
    except Exception as exc:
        logger.warning("music_recall failed: %s", exc)
        return f"music-curation recall failed: {exc}"
    _record_delegation("music_recall", "music_curation_memory", query, result.cost_usd)
    if not result.cross_references:
        return f"No similar prior generations found for: {query}"
    lines = [
        f"[{ref.reaction}] {ref.suggested_track_title or ref.entry_id[:8]}: {ref.style_field_excerpt[:160]}"
        for ref in result.cross_references
    ]
    return _truncate("Similar prior generations:\n" + "\n".join(lines))


@tool
async def music_generate(request: str) -> str:
    """Generate Suno music prompts via the music-curation agent (music-theory
    reasoning + the user's taste memory). Returns prompt(s) with reasoning. This
    spends LLM budget."""
    from music_curation import curate

    try:
        result = await curate(request, budget=_child_budget(), skip_question=True)
    except Exception as exc:
        logger.warning("music_generate failed: %s", exc)
        return f"music-curation generate failed: {exc}"
    _record_delegation("music_generate", "music_curation_memory", request, result.cost_usd)
    parts = [f"status={result.status} cost=${result.cost_usd:.4f}"]
    for i, prompt in enumerate(result.prompts, 1):
        title = result.suggested_titles[i - 1] if i <= len(result.suggested_titles) else f"Prompt {i}"
        parts.append(f"\n[{title}] style: {prompt.style_field}")
        if prompt.lyrics_field:
            parts.append(f"lyrics: {prompt.lyrics_field[:300]}")
    if result.theory_reasoning:
        parts.append("\nReasoning: " + result.theory_reasoning)
    return _truncate("\n".join(parts))


# ── Sub-agent tools: voiceover-direction ────────────────────────────────────────


@tool
async def voiceover_direct(script_path: str) -> str:
    """Run the voiceover-direction agent's FREE direction pass over a script.md:
    LLM-only delivery direction (pacing, emphasis, emotion, voice assignment). NO
    audio is synthesized and NO ElevenLabs/TTS money is spent — paid voiceover
    generation is a separate, deliberate step the orchestrator does not perform.
    Pass a repo-relative or absolute path to a script.md. Returns the direction
    reasoning and a per-section summary."""
    from voiceover_direction import direct

    try:
        result = await direct(script_path, budget=_child_budget())
    except Exception as exc:
        logger.warning("voiceover_direct failed: %s", exc)
        return f"voiceover-direction direct failed: {exc}"
    _record_delegation("voiceover_direct", "voiceover_direction_memory", str(script_path), result.cost_usd)
    parts = [
        f"status={result.status} cost=${result.cost_usd:.4f} "
        f"sections={len(result.directed_script.sections)}"
    ]
    if result.output_path:
        parts.append(f"output: {result.output_path}")
    if result.overall_reasoning:
        parts.append("\nReasoning: " + result.overall_reasoning)
    return _truncate("\n".join(parts))


@tool
async def voiceover_recall(query: str) -> str:
    """Recall prior voiceover-direction work WITHOUT directing or synthesizing
    anything (embedding-only, near-free): prior takes, confirmed direction lessons,
    ElevenLabs facts, and tutorial hits. Use to look up what's been directed or
    learned before."""
    from agent_runtime import get_memory_store
    from voiceover_direction import VoiceoverDirectionStore
    from voiceover_direction.retrieval import retrieve_context

    try:
        ms = get_memory_store()
        store = VoiceoverDirectionStore(ms)
        ctx = await retrieve_context(query, store, ms)
    except Exception as exc:
        logger.warning("voiceover_recall failed: %s", exc)
        return f"voiceover-direction recall failed: {exc}"
    _record_delegation("voiceover_recall", "voiceover_direction_memory", query, 0.0)
    if ctx.is_empty():
        return f"No prior voiceover-direction context found for: {query}"
    lines: list[str] = []
    for score, take in ctx.prior_takes[:4]:
        lines.append(f"[take {score:.3f}] {take.text[:160]}")
    for score, lesson in ctx.direction_lessons[:4]:
        lines.append(f"[lesson {score:.3f}] {lesson.statement[:160]}")
    for score, statement, _payload in ctx.elevenlabs_facts[:3]:
        lines.append(f"[fact {score:.3f}] {statement[:160]}")
    for score, hit in ctx.tutorial_hits[:3]:
        lines.append(f"[tutorial {score:.3f}] {hit[:160]}")
    return _truncate("Prior voiceover-direction context:\n" + "\n".join(lines))


# ── Sub-agent tools: concept-script (stateless — no collection) ──────────────────


def _render_concept(result) -> str:
    brief = result.brief
    parts = [f"status={result.status} cost=${result.cost_usd:.4f}"]
    if result.script_path:
        parts.append(f"script: {result.script_path}")
    parts.append(f"logline: {brief.logline}")
    if brief.sections:
        parts.append("sections: " + " | ".join(s.heading for s in brief.sections))
    return "\n".join(parts)


@tool
async def concept_draft(seeds: str) -> str:
    """Draft a new video concept script from rough seeds via the concept-script
    agent (free LLM ideation → an editable script.md brief). This agent is
    stateless — it holds no memory. Returns the logline and section headings."""
    from concept_script import draft

    try:
        result = await draft(seeds, budget=_child_budget())
    except Exception as exc:
        logger.warning("concept_draft failed: %s", exc)
        return f"concept-script draft failed: {exc}"
    _record_delegation("concept_draft", "concept_script", seeds, result.cost_usd)
    return _truncate(_render_concept(result))


@tool
async def concept_shape(transcript: str) -> str:
    """Shape an existing transcript into a structured video concept script via the
    concept-script agent (free LLM restructuring → an editable script.md brief).
    Stateless — no memory. Returns the logline and section headings."""
    from concept_script import shape

    try:
        result = await shape(transcript, budget=_child_budget())
    except Exception as exc:
        logger.warning("concept_shape failed: %s", exc)
        return f"concept-script shape failed: {exc}"
    _record_delegation("concept_shape", "concept_script", transcript, result.cost_usd)
    return _truncate(_render_concept(result))


# ── Sub-agent tools: visual-generation ───────────────────────────────────────────


@tool
async def visual_draft(intent: str) -> str:
    """Craft a visual-generation spec from an intent via the visual-generation
    agent's FREE prompt-craft pass (LLM-only: prompt, model/LoRA selection, tutor
    notes). This does NOT run diffusion — GPU/RunPod generation is real spend and
    is a separate, deliberate step the orchestrator does not perform. Returns the
    crafted spec plus advisories (missing models, research offer)."""
    from visual_generation import draft

    try:
        result = await draft(intent, budget=_child_budget())
    except Exception as exc:
        logger.warning("visual_draft failed: %s", exc)
        return f"visual-generation draft failed: {exc}"
    _record_delegation("visual_draft", "visual_generation_memory", intent, result.cost_usd)
    spec = result.spec
    parts = [f"status={result.status} cost=${result.cost_usd:.4f}"]
    if spec.heading:
        parts.append(f"heading: {spec.heading}")
    if spec.model:
        parts.append(f"model: {spec.model}")
    parts.append(f"prompt: {spec.prompt[:400]}")
    if result.missing_models:
        parts.append("missing models: " + ", ".join(result.missing_models))
    if result.research_offer:
        parts.append("research offer: " + result.research_offer)
    if result.overall_reasoning:
        parts.append("\nReasoning: " + result.overall_reasoning)
    return _truncate("\n".join(parts))


@tool
async def visual_recall(query: str) -> str:
    """Recall prior visual-generation work WITHOUT crafting or generating anything
    (embedding-only, near-free): prior generations, technique lessons, and workflow
    templates. Use to look up what's been made or learned before."""
    from visual_generation import recall, render_recall

    try:
        gens, lessons, templates = await recall(query)
    except Exception as exc:
        logger.warning("visual_recall failed: %s", exc)
        return f"visual-generation recall failed: {exc}"
    _record_delegation("visual_recall", "visual_generation_memory", query, 0.0)
    if not (gens or lessons or templates):
        return f"No prior visual-generation work found for: {query}"
    return _truncate(render_recall(gens, lessons, templates))


# ── Sub-agent tools: technique-research ──────────────────────────────────────────


@tool
async def technique_recall(query: str) -> str:
    """Recall prior technique-research findings WITHOUT identifying or delegating
    anything (embedding-only, near-free): curated per-technique findings (technique,
    why it matters, how to apply, toolset fit). Use to look up techniques already
    researched for past goals."""
    from technique_research import recall

    try:
        results = await recall(query)
    except Exception as exc:
        logger.warning("technique_recall failed: %s", exc)
        return f"technique-research recall failed: {exc}"
    _record_delegation("technique_recall", "technique_research_outputs", query, 0.0)
    if not results:
        return f"No technique findings found for: {query}"
    lines = [
        f"[{score:.3f}] {f.technique}: {f.description[:240]}" for score, f in results
    ]
    return _truncate("Prior technique findings:\n" + "\n".join(lines))


@tool
async def technique_identify(goal: str) -> str:
    """Run the technique-research agent on a creative goal: identify the prioritized
    technique domains the goal needs, check existing knowledge, and (auto-approving
    gaps within budget) delegate gathering to tutorial-research, then curate findings.
    This SPENDS budget (identification + possible tutorial-research delegations) — use
    when the user wants to know what techniques a 'video/images like X' goal involves.
    Returns the curated techniques and where the report was written."""
    from technique_research import identify
    from technique_research.models import IdentificationInput

    try:
        result = await identify(
            IdentificationInput(goal=goal), budget=_child_budget(), approval=None
        )
    except Exception as exc:
        logger.warning("technique_identify failed: %s", exc)
        return f"technique-research identify failed: {exc}"
    _record_delegation("technique_identify", "technique_research_outputs", goal, result.cost_usd)
    parts = [
        f"status={result.status} cost=${result.cost_usd:.4f} "
        f"scope={result.report.scope} findings={len(result.report.techniques)}"
    ]
    if result.report_path:
        parts.append(f"report: {result.report_path}")
    for t in result.report.techniques:
        line = f"\n• {t.technique}: {t.why_it_matters or t.description}"
        if t.upgrade_flag:
            line += f" [⬆ paid/Studio: {t.upgrade_flag}]"
        parts.append(line)
    return _truncate("\n".join(parts))


# ── Vector-DB diagnostics (diagnose-only) ────────────────────────────────────────
# The orchestrator audits the Qdrant layer but NEVER writes to it. These tools do
# read-only structural inspection + a behavioral probe, then write a diagnostic
# report. The fix is delegated to the owning agent (see diagnostics.delegate_
# remediation), which performs the write — but no agent registers a handler yet, so
# reports are manual work orders. The model drives: it reads an agent's collection /
# filter / threshold / embedding model from source via read_file/grep, inspects and
# probes the collection, then writes the report.


@tool
async def inspect_collection(collection: str) -> str:
    """Read-only structural inspection of a Qdrant collection: existence, point
    count, vector size/distance, and a small sample of payload keys. Use this to
    check whether an agent's memory collection exists and holds data before probing
    its retrieval. Read-only — never writes."""
    from agent_runtime import get_memory_store

    try:
        ms = get_memory_store()
        info = await ms.get_collection_info(collection)
        if info is None:
            return f"Collection '{collection}' does not exist."
        sample = await ms.sample_points(collection, limit=3)
    except Exception as exc:
        logger.warning("inspect_collection failed: %s", exc)
        return f"inspect_collection failed ({exc.__class__.__name__}): {exc}"
    lines = [
        f"collection={info['name']} status={info['status']} "
        f"points={info['points_count']} indexed_vectors={info['indexed_vectors_count']} "
        f"vector_size={info['vector_size']} distance={info['distance']}"
    ]
    for pid, payload in sample:
        keys = ", ".join(sorted(payload.keys())[:12])
        lines.append(f"  [{pid[:8]}] keys: {keys}")
    return _truncate("\n".join(lines))


@tool
async def probe_collection(
    collection: str,
    query: str,
    expected_point_id: str | None = None,
    multimodal: bool = False,
    threshold: float = 0.5,
) -> str:
    """Behavioral probe: embed a query that SHOULD retrieve a known point and check
    whether it returns above `threshold`. Set multimodal=True for image-embedded
    collections (visual-generation generations use voyage-multimodal-3; everything
    else uses voyage-3-large). This is the ONLY way to catch a cross-model
    embedding-space mismatch — when an expected point exists in the collection but the
    probe can't surface it, the stored vectors were written in a different embedding
    space. Read-only — never writes."""
    from orchestrator.diagnostics import behavioral_probe

    try:
        result = await behavioral_probe(
            collection, query,
            expected_point_id=expected_point_id,
            multimodal=multimodal,
            threshold=threshold,
        )
    except Exception as exc:
        logger.warning("probe_collection failed: %s", exc)
        return f"probe_collection failed ({exc.__class__.__name__}): {exc}"
    parts = [
        f"collection={collection} model={result.model} threshold={threshold} "
        f"top_score={result.top_score:.3f}"
    ]
    for pid, score, _payload in result.hits[:5]:
        parts.append(f"  [{score:.3f}] {pid}")
    if expected_point_id is not None:
        parts.append(
            f"expected={expected_point_id} "
            f"returned_above_threshold={result.expected_returned_above_threshold} "
            f"present_in_collection={result.expected_present_in_collection}"
        )
        if result.cross_model_suspected:
            parts.append(
                "⚠ CROSS-MODEL MISMATCH SUSPECTED: the expected point exists in the "
                "collection but the probe (this embedding space) cannot retrieve it — "
                "the stored vectors were likely written with a different Voyage model."
            )
    return _truncate("\n".join(parts))


@tool
def write_diagnostic_report(
    collection: str,
    owning_agent: str,
    symptom: str,
    diagnosis: str,
    evidence: dict,
    proposed_fix: str,
) -> str:
    """Write a diagnose-only vector-DB diagnostic report to the reports vault
    (<vault>/diagnostics/). `evidence` should carry the filter/threshold/embedding
    model read from the agent's source PLUS the actual payloads/scores observed via
    inspect_collection / probe_collection. The report is written with status=open.
    The orchestrator never fixes the issue itself — the fix is delegated to the owning
    agent, which performs the write under its own ownership; until that agent exposes a
    remediation entry point, this report is the actionable work order."""
    from orchestrator.diagnostics import (
        DiagnosticReport,
        get_remediation_handler,
        write_diagnostic_report as _write,
    )

    report = DiagnosticReport(
        collection=collection,
        owning_agent=owning_agent,
        symptom=symptom,
        diagnosis=diagnosis,
        evidence=evidence or {},
        proposed_fix=proposed_fix,
    )
    try:
        path = _write(report)
    except Exception as exc:
        logger.warning("write_diagnostic_report failed: %s", exc)
        return f"write_diagnostic_report failed ({exc.__class__.__name__}): {exc}"
    has_handler = get_remediation_handler(owning_agent) is not None
    remediation = (
        f"a remediation handler is registered for {owning_agent}; the fix can be delegated"
        if has_handler
        else f"no remediation handler is registered for {owning_agent} — this report is a "
        "manual work order (the orchestrator does not write to Qdrant)"
    )
    return f"Diagnostic report written (status=open): {path}\n{remediation}"


def all_tools() -> list:
    """The v1 tool set bound to the orchestrator's Sonnet model."""
    return [
        search_knowledge,
        read_file,
        grep,
        tutorial_retrieve,
        research_tutorials,
        music_recall,
        music_generate,
        voiceover_direct,
        voiceover_recall,
        concept_draft,
        concept_shape,
        visual_draft,
        visual_recall,
        technique_recall,
        technique_identify,
        inspect_collection,
        probe_collection,
        write_diagnostic_report,
    ]
