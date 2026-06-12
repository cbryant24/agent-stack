"""LLM chains: reference assessment, technique identification, finding curation.

All three route Anthropic `response.usage` through `_record_llm` so the active
BudgetTracker accrues cost (the bridge pattern from music-curation; without it
cost aggregation reads $0). Claude is vision-capable — reference images are
analysed directly as content blocks in the identification call, never embedded.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic
from anthropic.types import Message

from agent_runtime.tracing import record_llm_call

from technique_research.constants import (
    MAX_ASSESS_TOKENS,
    MAX_CURATION_TOKENS,
    MAX_IDENTIFY_TOKENS,
    MODEL_IDENTIFY,
)
from technique_research.models import (
    GroundedReference,
    IdentificationInput,
    Scope,
    TechniqueDomain,
    TechniqueFinding,
)

logger = logging.getLogger(__name__)

# Pricing fallback only used when no tracker is active (mirrors music-curation).
_PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (0.80, 4.0),
}


def _compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    in_price, out_price = _PRICING.get(model, (3.0, 15.0))
    return (input_tokens * in_price + output_tokens * out_price) / 1_000_000


def _record_llm(model: str, input_tokens: int, output_tokens: int) -> None:
    """Route LLM cost through the active BudgetTracker when present, else emit
    directly. Copied verbatim from music_curation/chains.py — see its docstring."""
    from agent_runtime.budget import get_current_tracker

    tracker = get_current_tracker()
    if tracker is not None:
        tracker.add_llm_cost(model, input_tokens, output_tokens)
    else:
        cost = _compute_cost(model, input_tokens, output_tokens)
        record_llm_call(model, input_tokens, output_tokens, cost)


_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _image_block(path: Path) -> dict[str, Any] | None:
    """Load an image file into an Anthropic vision content block, or None if it
    can't be read / isn't a supported type."""
    suffix = path.suffix.lower()
    media_type = _MEDIA_TYPES.get(suffix)
    if media_type is None:
        logger.warning("Skipping unsupported image type: %s", path)
        return None
    try:
        data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    except Exception as exc:
        logger.warning("Could not read image %s: %s", path, exc)
        return None
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": data},
    }


def _parse_json(response: Message) -> dict[str, Any]:
    text = response.content[0].text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    return json.loads(text)


# ── Stage 1a: assess the reference ────────────────────────────────────────────

_ASSESS_SYSTEM = """\
You assess whether a creative goal's reference is well-specified enough to identify \
techniques directly, or whether it names something under-specified (e.g. "like Xenoz \
edits", "that A24 look") that warrants a quick web search to understand first.

Respond with EXACTLY this JSON and nothing else:
{"needs_grounding": true|false, "tavily_query": "..."|null, "preliminary_summary": "..."}

- needs_grounding=true ONLY when the reference names a creator/work/style you cannot \
characterise confidently from the goal text alone, AND a web search would resolve it.
- A self-contained, descriptive goal ("a fast-cut AMV with speed ramps") needs no \
grounding — return false and a null query.
- preliminary_summary: one or two sentences on what the reference appears to be."""


async def assess_reference(
    inp: IdentificationInput,
    url_metadata: dict[str, Any] | None,
    client: AsyncAnthropic,
) -> dict[str, Any]:
    parts = [f"Goal: {inp.goal}"]
    if inp.domain:
        parts.append(f"Stated video type/domain: {inp.domain}")
    if url_metadata:
        parts.append(
            "Reference video metadata: "
            f"title={url_metadata.get('title')!r}, "
            f"uploader={url_metadata.get('uploader')!r}, "
            f"description={url_metadata.get('description', '')[:400]!r}"
        )
    if inp.images:
        parts.append(f"{len(inp.images)} reference image(s) are attached to the identification step.")

    response = await client.messages.create(
        model=MODEL_IDENTIFY,
        max_tokens=MAX_ASSESS_TOKENS,
        system=_ASSESS_SYSTEM,
        messages=[{"role": "user", "content": "\n".join(parts)}],
    )
    _record_llm(MODEL_IDENTIFY, response.usage.input_tokens, response.usage.output_tokens)
    try:
        parsed = _parse_json(response)
    except (json.JSONDecodeError, AttributeError, IndexError):
        return {"needs_grounding": False, "tavily_query": None, "preliminary_summary": ""}
    return {
        "needs_grounding": bool(parsed.get("needs_grounding")),
        "tavily_query": parsed.get("tavily_query"),
        "preliminary_summary": parsed.get("preliminary_summary", ""),
    }


# ── Stage 1b: identify techniques ─────────────────────────────────────────────

_IDENTIFY_SYSTEM = """\
You are a video-technique analyst. Given a creative goal (optionally with reference \
images, reference-video metadata, and web context), identify the PRIORITIZED set of \
technique DOMAINS the goal requires — not how to do them, just which ones matter and why.

You decide SCOPE: "editing" (post-production craft — cuts, color, motion, sound) vs \
"generation" (creating imagery — ComfyUI/Flux/WAN/LoRA territory) vs "both". Infer it \
from the goal ("a video like X" → editing; "images like X" → generation) UNLESS a scope \
is explicitly given, in which case honour it.

Ground your reasoning in the director's toolset when provided, but identify domains by \
what the GOAL needs, not by what the toolset happens to make easy.

Respond with EXACTLY this JSON and nothing else:
{
  "scope": "editing"|"generation"|"both",
  "grounded_reference_summary": "what the reference is and what defines its look/feel",
  "domains": [
    {"name": "...", "why_it_matters": "why THIS goal needs it",
     "priority": 1, "scope": "editing"|"generation",
     "search_query": "a focused query to find tutorials on this domain"}
  ]
}
Order domains by priority (1 = highest). Keep to the techniques that genuinely matter \
(typically 3-6). search_query is what would be handed to a tutorial researcher."""


async def identify_techniques(
    inp: IdentificationInput,
    grounded: GroundedReference,
    toolset_ctx: str,
    prior_findings_summary: str,
    client: AsyncAnthropic,
) -> tuple[list[TechniqueDomain], str, Scope]:
    text_parts = [f"Goal: {inp.goal}"]
    if inp.domain:
        text_parts.append(f"Stated video type/domain: {inp.domain}")
    if inp.scope:
        text_parts.append(f"Scope is EXPLICITLY set to: {inp.scope} (honour this).")
    else:
        text_parts.append("Scope is not given — infer it from the goal.")
    if grounded.summary:
        text_parts.append(f"Reference understanding: {grounded.summary}")
    if grounded.url_metadata:
        m = grounded.url_metadata
        text_parts.append(
            f"Reference video: title={m.get('title')!r}, uploader={m.get('uploader')!r}, "
            f"description={m.get('description', '')[:500]!r}"
        )
    if grounded.exemplars:
        text_parts.append("Web context on the reference:\n" + "\n".join(f"- {e}" for e in grounded.exemplars))
    if toolset_ctx:
        text_parts.append(toolset_ctx)
    if prior_findings_summary:
        text_parts.append("Already-known related techniques (prior findings):\n" + prior_findings_summary)
    if inp.images:
        text_parts.append("Reference image(s) follow — analyse them as part of identifying the look.")

    content: list[dict[str, Any]] = [{"type": "text", "text": "\n".join(text_parts)}]
    for img in inp.images:
        block = _image_block(img)
        if block is not None:
            content.append(block)

    response = await client.messages.create(
        model=MODEL_IDENTIFY,
        max_tokens=MAX_IDENTIFY_TOKENS,
        system=_IDENTIFY_SYSTEM,
        messages=[{"role": "user", "content": content}],
    )
    _record_llm(MODEL_IDENTIFY, response.usage.input_tokens, response.usage.output_tokens)
    data = _parse_json(response)

    # Explicit --scope is authoritative (prevents misrouting); otherwise take the
    # model's inference, defaulting to editing.
    scope: Scope = inp.scope or data.get("scope") or "editing"
    if scope not in ("editing", "generation", "both"):
        scope = "editing"
    summary = data.get("grounded_reference_summary", grounded.summary)

    domains: list[TechniqueDomain] = []
    for d in data.get("domains", []):
        name = (d.get("name") or "").strip()
        if not name:
            continue
        d_scope = d.get("scope") if d.get("scope") in ("editing", "generation") else (
            scope if scope != "both" else "editing"
        )
        domains.append(
            TechniqueDomain(
                name=name,
                why_it_matters=d.get("why_it_matters", ""),
                priority=int(d.get("priority", 1) or 1),
                scope=d_scope,
                search_query=d.get("search_query") or name,
            )
        )
    domains.sort(key=lambda x: x.priority)
    return domains, summary, scope


# ── Stage 4: curate findings ──────────────────────────────────────────────────

_CURATE_SYSTEM = """\
You curate per-technique FINDINGS — relevance decisions for a specific creative goal, \
grounded in gathered material and the director's actual toolset. For each technique \
produce a decision-level finding, not a tutorial.

Rules:
- how-to-apply must be grounded in the director's toolset (provided). Do NOT invent \
tools the director doesn't have.
- Set "upgrade_flag" to a short note ONLY when a technique is materially faster or only \
possible in a paid/Studio tool the director may not own; otherwise null. Never a sales pitch.
- Stay at decision/application altitude — where it applies and how, not step-by-step.

Respond with EXACTLY this JSON and nothing else:
{
  "techniques": [
    {"technique": "...", "description": "...", "why_it_matters": "for THIS goal",
     "application_notes": "how to apply with the director's toolset",
     "toolset_fit": "which owned tool(s) and how",
     "upgrade_flag": "..."|null}
  ]
}"""


async def curate_findings(
    goal: str,
    scope: Scope,
    domains: list[TechniqueDomain],
    material_by_domain: dict[str, str],
    toolset_ctx: str,
    client: AsyncAnthropic,
) -> list[dict[str, Any]]:
    """Return raw finding dicts (the agent attaches source_refs / context). One
    call over all domains and their resolved material."""
    parts = [f"Creative goal: {goal}", f"Scope: {scope}", ""]
    if toolset_ctx:
        parts.append(toolset_ctx)
        parts.append("")
    parts.append("Techniques to curate, with the material gathered for each:")
    for d in domains:
        parts.append(f"\n### {d.name} (priority {d.priority})")
        parts.append(f"Why identified: {d.why_it_matters}")
        material = material_by_domain.get(d.name, "").strip()
        parts.append("Gathered material:\n" + (material if material else "(no gathered material — curate from general expertise and the toolset)"))

    response = await client.messages.create(
        model=MODEL_IDENTIFY,
        max_tokens=MAX_CURATION_TOKENS,
        system=_CURATE_SYSTEM,
        messages=[{"role": "user", "content": "\n".join(parts)}],
    )
    _record_llm(MODEL_IDENTIFY, response.usage.input_tokens, response.usage.output_tokens)
    try:
        data = _parse_json(response)
    except (json.JSONDecodeError, AttributeError, IndexError):
        return []
    return data.get("techniques", [])
