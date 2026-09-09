"""Stage 3 — one Claude Sonnet vision call per segment.

Frames are sent via `LLMProvider.complete(image_paths=...)`. The provider
(anthropic) packs them into base64 image blocks. The bridge `_record_llm`
routes token usage into the surrounding BudgetTracker if one is active,
mirroring `visual_generation/chains.py:_record_llm`.
"""

from __future__ import annotations

from pathlib import Path

from agent_runtime.llm import LLMProvider
from agent_runtime.tracing.decorators import record_llm_call

from video_clipping.constants import PHASE1_MODEL_ID, VISION_MAX_TOKENS
from video_clipping.exceptions import VisionError
from video_clipping.models import Segment

_VISION_SYSTEM_PROMPT = """You are a video-shot analyst.

You will be shown 1–8 frames sampled uniformly across a short video segment.
Return a compact structured summary of what is visible — the reader is another
LLM that must decide whether to keep the segment for a highlight reel.

Cover, in this order and with plain prose (no bullet points, no headers):
- Setting: location cues, indoor/outdoor, time of day.
- Subjects: people (count, activity), animals, notable objects.
- Camera: fixed / handheld / moving; wide / medium / close.
- Notable action or change across frames.
- Any obvious quality issues (blur, dim, obstruction, upside down).

Keep the whole reply under 120 words. No preamble.
"""


def _record_llm(model: str, input_tokens: int, output_tokens: int) -> None:
    """Route token usage through the active BudgetTracker; fall back to a bare trace."""
    from agent_runtime.budget import get_current_tracker

    tracker = get_current_tracker()
    if tracker is not None:
        tracker.add_llm_cost(model, input_tokens, output_tokens)
    else:
        record_llm_call(model, input_tokens, output_tokens, 0.0)


async def summarize_segment(
    provider: LLMProvider,
    seg: Segment,
    frame_paths: list[Path],
) -> str:
    user_text = (
        f"Segment {seg.segment_id}: [{seg.start:.2f}s → {seg.end:.2f}s] "
        f"({seg.duration:.2f}s). {len(frame_paths)} frame(s) attached, evenly sampled."
    )
    try:
        comp = await provider.complete(
            system=_VISION_SYSTEM_PROMPT,
            user_text=user_text,
            image_paths=frame_paths,
            model=PHASE1_MODEL_ID,
            max_tokens=VISION_MAX_TOKENS,
        )
    except Exception as exc:
        raise VisionError(f"vision call failed for {seg.segment_id}: {exc}") from exc
    _record_llm(comp.model, comp.input_tokens, comp.output_tokens)
    return comp.text.strip()
