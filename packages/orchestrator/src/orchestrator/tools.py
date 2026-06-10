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
    ]
