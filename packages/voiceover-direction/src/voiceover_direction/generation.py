"""Generation — the paid step, with the option-B re-direction fold-in.

`generate` is split into two phases so the soft-inform gate can show the *revised* markup:

- `plan_generation` — resolve each target section to the exact text that will be spoken. If a
  section's last take carries a `report` note (and not `--raw`), fold in a section-scoped
  re-direction (a Claude call) based on that last take. This phase carries the Claude cost,
  guarded by `GENERATE_BUDGET`'s cost cap.
- `spend_generation` — drive the resolved plan: TTS → audio file + a pending take. The
  character spend is recorded only as a span attribute, NEVER in `BudgetEnvelope`.

The CLI runs plan → gate → spend (the gate is interactive there). `generate` is a combined,
prompt-free convenience entry (plan + auto-spend) for library use. The two phases run as two
traced runs, which mirrors the two orthogonal budgets: a plan run (Claude cost) and a spend
run (character span attribute). Iteration lives in `direct`/the fold-in; generation is a
deliberate commitment.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_runtime import (
    BudgetEnvelope,
    BudgetExhaustedError,
    BudgetTracker,
    MemoryStore,
    TracePersister,
    get_config,
    get_memory_store,
    notify_run_complete,
    render_run_report,
)
from agent_runtime.tracing.decorators import record_memory_write
from anthropic import AsyncAnthropic
from opentelemetry import trace

from voiceover_direction.chains import redirect_section
from voiceover_direction.constants import (
    CHARACTERS_SPAN_ATTR,
    COLLECTION_NAME,
    DEFAULT_MODEL,
    DEFAULT_OUTPUT_FORMAT,
    GENERATE_BUDGET,
)
from voiceover_direction.directed_script import read_directed_script
from voiceover_direction.elevenlabs_client import ElevenLabsClient
from voiceover_direction.models import (
    DirectedScript,
    DirectedSection,
    GenerationResult,
    Take,
    VoiceoverResult,
    _new_id,
)
from voiceover_direction.retrieval import retrieve_context
from voiceover_direction.store import VoiceoverDirectionStore

logger = logging.getLogger(__name__)

AGENT_NAME = "voiceover-direction"

_TAG_RE = re.compile(r"\[([^\]]+)\]")


# ── Plan structures ──────────────────────────────────────────────────────────


@dataclass
class SectionPlan:
    """One resolved section ready to spend: the exact text + how it was resolved."""

    section_id: str
    heading: str
    text: str
    voice_id: str
    model: str
    settings: dict[str, Any]
    char_count: int
    was_redirected: bool = False
    note: str | None = None  # the note that drove re-direction (for the gate display)
    base_take_id: str | None = None  # lineage parent (the section's last take)
    base_chain_root_id: str = ""


@dataclass
class GenerationPlan:
    """The result of the plan phase: what will be spent, plus the Claude re-direction cost."""

    run_id: str
    project_id: str
    domain: str | None
    plans: list[SectionPlan] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    status: str = "completed"
    cost_usd: float = 0.0
    wall_time_sec: float = 0.0


# ── Helpers ──────────────────────────────────────────────────────────────────


def select_sections(
    directed: DirectedScript,
    *,
    section_id: str | None = None,
    all_sections: bool = False,
) -> list[DirectedSection]:
    """Resolve the target sections. Raises ValueError on an unknown id or no selection."""
    if all_sections:
        return list(directed.sections)
    if section_id is not None:
        match = [s for s in directed.sections if s.section_id == section_id]
        if not match:
            known = ", ".join(s.section_id for s in directed.sections) or "(none)"
            raise ValueError(f"Unknown section_id {section_id!r}. Known sections: {known}")
        return match
    raise ValueError("Specify a section (--section <id>) or --all.")


def _extract_emotion_tags(text: str) -> list[str]:
    """Pull inline audio tags (bracketed) from directed text, de-duplicated in order.

    These tags are part of the exact string sent to ElevenLabs and they bill, so they
    are recorded on the take.
    """
    seen: dict[str, None] = {}
    for m in _TAG_RE.finditer(text):
        tag = f"[{m.group(1)}]"
        seen.setdefault(tag, None)
    return list(seen)


def _audio_path(project_id: str, section_id: str, take_id: str, output_format: str) -> Path:
    """Absolute path for the audio file, with parent dirs created."""
    ext = output_format.split("_")[0]
    path = (
        get_config().agent_data_dir
        / "voiceover"
        / "audio"
        / project_id
        / f"{section_id}-{take_id}.{ext}"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _record_characters(cumulative: int) -> None:
    """Record characters consumed as a span attribute (never a budget dimension)."""
    trace.get_current_span().set_attribute(CHARACTERS_SPAN_ATTR, cumulative)


# ── Plan phase ───────────────────────────────────────────────────────────────


async def plan_generation(
    directed_path: str | Path,
    *,
    section_id: str | None = None,
    all_sections: bool = False,
    raw: bool = False,
    budget: BudgetEnvelope | None = None,
    store: VoiceoverDirectionStore | None = None,
    memory_store: MemoryStore | None = None,
    llm_client: AsyncAnthropic | None = None,
) -> GenerationPlan:
    """Resolve each target section to the text that will be spoken.

    For a section whose last take carries a note (and not `raw`), fold in a section-scoped
    re-direction based on that last take — the Claude cost lands here, guarded by the cost
    cap. Sections without a voice are skipped. Makes no character spend.
    """
    directed = read_directed_script(Path(directed_path))
    targets = select_sections(directed, section_id=section_id, all_sections=all_sections)

    memory_store = memory_store or get_memory_store()
    store = store or VoiceoverDirectionStore(memory_store)
    await store.ensure_collection()

    status = "completed"
    tracker_ref: BudgetTracker | None = None
    run_id = ""
    cost_usd = 0.0
    wall_time_sec = 0.0
    plans: list[SectionPlan] = []
    skipped: list[str] = []

    try:
        async with BudgetTracker(budget or GENERATE_BUDGET, AGENT_NAME) as tracker:
            tracker_ref = tracker
            run_id = tracker.run_id

            with TracePersister(agent=AGENT_NAME, run_id=run_id):
                for section in targets:
                    tracker.check_budget()
                    if not section.voice_id:
                        skipped.append(section.section_id)
                        continue

                    prev = await store.latest_take_for_section(directed.project_id, section.section_id)

                    if not raw and prev is not None and prev.notes:
                        # Fold in the note: re-direct from the LAST take (compounding chain).
                        tracker.check_budget()
                        ctx = await retrieve_context(
                            prev.text, store, memory_store, section_id=section.section_id
                        )
                        client = llm_client or AsyncAnthropic(api_key=get_config().anthropic_api_key)
                        revised = await redirect_section(
                            prev, section.heading, prev.notes, ctx, store.list_voices(), client
                        )
                        final = revised
                        was_redirected = True
                        note = prev.notes
                    else:
                        # --raw, or no note: speak the file's section markup verbatim (Step 3).
                        final = section
                        was_redirected = False
                        note = None

                    voice_id = final.voice_id or section.voice_id
                    plans.append(
                        SectionPlan(
                            section_id=section.section_id,
                            heading=section.heading,
                            text=final.text,
                            voice_id=voice_id,
                            model=final.model or DEFAULT_MODEL,
                            settings=final.settings,
                            char_count=len(final.text),
                            was_redirected=was_redirected,
                            note=note,
                            base_take_id=prev.entry_id if prev else None,
                            base_chain_root_id=prev.chain_root_id if prev else "",
                        )
                    )

    except BudgetExhaustedError:
        status = "partial"

    if tracker_ref is not None:
        snap = tracker_ref._consumption
        cost_usd = snap.cost_usd
        wall_time_sec = snap.wall_time_sec

    return GenerationPlan(
        run_id=run_id,
        project_id=directed.project_id,
        domain=directed.domain,
        plans=plans,
        skipped=skipped,
        status=status,
        cost_usd=cost_usd,
        wall_time_sec=wall_time_sec,
    )


# ── Spend phase ──────────────────────────────────────────────────────────────


async def spend_generation(
    plan: GenerationPlan,
    *,
    output_format: str = DEFAULT_OUTPUT_FORMAT,
    usage_remaining: int | None = None,
    budget: BudgetEnvelope | None = None,
    store: VoiceoverDirectionStore | None = None,
    tts_client: ElevenLabsClient | None = None,
) -> GenerationResult:
    """Drive a resolved plan: TTS → audio file + pending take, per section.

    Makes no LLM call (cost_usd stays 0 — the character spend is orthogonal to the budget).
    """
    store = store or VoiceoverDirectionStore(get_memory_store())
    await store.ensure_collection()
    tts_client = tts_client or ElevenLabsClient()
    data_dir = get_config().agent_data_dir

    status = "completed"
    tracker_ref: BudgetTracker | None = None
    run_id = ""
    cost_usd = 0.0
    wall_time_sec = 0.0
    items_processed = 0
    results: list[VoiceoverResult] = []
    cumulative = 0

    try:
        async with BudgetTracker(budget or GENERATE_BUDGET, AGENT_NAME) as tracker:
            tracker_ref = tracker
            run_id = tracker.run_id

            with TracePersister(agent=AGENT_NAME, run_id=run_id):
                for p in plan.plans:
                    tracker.check_budget()
                    take_id = _new_id()

                    audio = await tts_client.synthesize(
                        p.text,
                        p.voice_id,
                        model_id=p.model,
                        output_format=output_format,
                        voice_settings=p.settings or None,
                    )
                    abs_path = _audio_path(plan.project_id, p.section_id, take_id, output_format)
                    abs_path.write_bytes(audio)
                    rel_path = abs_path.relative_to(data_dir)

                    take = Take(
                        entry_id=take_id,
                        text=p.text,
                        voice_id=p.voice_id,
                        model=p.model,
                        settings=p.settings,
                        emotion_tags=_extract_emotion_tags(p.text),
                        character_count=p.char_count,
                        audio_path=str(rel_path),  # relative to agent_data_dir (portable)
                        section_id=p.section_id,
                        project_id=plan.project_id,
                        domain=plan.domain,
                        parent_take_id=p.base_take_id,
                        chain_root_id=p.base_chain_root_id,
                    )
                    await store.upsert_take(take)
                    record_memory_write(COLLECTION_NAME, 1)

                    cumulative += p.char_count
                    _record_characters(cumulative)
                    tracker.add_item_processed()
                    items_processed += 1

                    remaining_after = (
                        usage_remaining - cumulative if usage_remaining is not None else None
                    )
                    results.append(
                        VoiceoverResult(
                            take_id=take.entry_id,
                            audio_path=str(abs_path),  # absolute, for on-screen use
                            character_cost=p.char_count,
                            remaining_characters=remaining_after,
                        )
                    )

    except BudgetExhaustedError:
        status = "partial"

    if tracker_ref is not None:
        snap = tracker_ref._consumption
        cost_usd = snap.cost_usd
        wall_time_sec = snap.wall_time_sec

    report_path: Path | None = None
    if run_id:
        try:
            report_path = render_run_report(run_id, AGENT_NAME)
        except FileNotFoundError:
            pass
        notify_run_complete(AGENT_NAME, run_id, status, cost_usd)

    return GenerationResult(
        results=results,
        skipped=plan.skipped,
        run_id=run_id,
        status=status,
        items_processed=items_processed,
        wall_time_sec=wall_time_sec,
        cost_usd=cost_usd,
        report_path=report_path,
    )


# ── Combined entry (prompt-free; library convenience + backward compatibility) ─


async def generate(
    directed_path: str | Path,
    *,
    section_id: str | None = None,
    all_sections: bool = False,
    raw: bool = False,
    output_format: str = DEFAULT_OUTPUT_FORMAT,
    budget: BudgetEnvelope | None = None,
    usage_remaining: int | None = None,
    store: VoiceoverDirectionStore | None = None,
    memory_store: MemoryStore | None = None,
    llm_client: AsyncAnthropic | None = None,
    tts_client: ElevenLabsClient | None = None,
) -> GenerationResult:
    """Plan then spend in one call (no gate). The soft-inform gate is the CLI's job.

    The returned result surfaces the plan's Claude re-direction cost in `cost_usd` (> 0 only
    when a fold-in fired); the character spend never enters the budget.
    """
    plan = await plan_generation(
        directed_path,
        section_id=section_id,
        all_sections=all_sections,
        raw=raw,
        budget=budget,
        store=store,
        memory_store=memory_store,
        llm_client=llm_client,
    )
    result = await spend_generation(
        plan,
        output_format=output_format,
        usage_remaining=usage_remaining,
        budget=budget,
        store=store,
        tts_client=tts_client,
    )
    # Surface the Claude re-direction cost on the combined result; mark partial if either
    # phase was budget-truncated. (Characters never contribute to cost_usd.)
    result.cost_usd = plan.cost_usd
    if plan.status == "partial":
        result.status = "partial"
    return result


def plan_generation_sync(directed_path: str | Path, **kwargs: Any) -> GenerationPlan:
    """Synchronous wrapper for plan_generation()."""
    return asyncio.run(plan_generation(directed_path, **kwargs))


def spend_generation_sync(plan: GenerationPlan, **kwargs: Any) -> GenerationResult:
    """Synchronous wrapper for spend_generation()."""
    return asyncio.run(spend_generation(plan, **kwargs))


def generate_sync(directed_path: str | Path, **kwargs: Any) -> GenerationResult:
    """Synchronous wrapper for generate()."""
    return asyncio.run(generate(directed_path, **kwargs))
