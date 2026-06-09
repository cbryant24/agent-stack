"""The draft craft chain (Sonnet) — the free, infinitely-iterable prompt-craft loop.

Given a creative intent, the retrieved three-collection context, the chosen
workflow template's available slots, and the registry's models, the chain emits
one settled generation spec: prompt, negative (only where the template has a
negative slot), a model-agnostic settings dict (only keys the template's slots
accept — e.g. flux_guidance only when the template declares it), model, seed
strategy, dimensions, LoRA stack, and a concise tutor rationale that cites the
user's own retrieved technique lessons. No ComfyUI call, no GPU — this is free.
"""

from __future__ import annotations

import json
import logging
import re

from anthropic import AsyncAnthropic
from anthropic.types import Message

from agent_runtime.tracing import record_llm_call

from visual_generation.constants import MAX_DRAFT_TOKENS, MODEL_DIRECTOR
from visual_generation.models import ModelAsset, WorkflowTemplate
from visual_generation.retrieval import RetrievedContext, build_context_prompt

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """\
You are an expert diffusion prompt-crafter and platform tutor working with ComfyUI
(Flux, SDXL, WAN). Given a creative intent, you craft ONE settled generation spec.

You are also a TUTOR: keep a concise rationale that explains the key settings
choices in plain language, and when the context surfaces the user's OWN technique
lessons, cite them back ("you noted CFG>7 washed skin on this checkpoint").

Honor the template's available slots — they tell you what is parameterizable:
- Only include a `negative_prompt` if "negative" is an available slot. Flux
  templates have NO negative slot and run CFG≈1.0 — do not invent a negative.
- Only include `flux_guidance` in settings if "flux_guidance" is an available
  slot (Flux's guidance replaces the negative prompt as the control).
- Only set settings keys that correspond to available slots
  (steps/cfg/sampler/scheduler/denoise/flux_guidance). Omit knobs you have no
  reason to set — {} is fine.

Pick `model` and any LoRAs BY NAME from the available-models list (never invent a
filename). If the list is empty, set model to null and describe the desired model
in the rationale.

When context is provided:
- [PRIOR GENERATION: reaction=LOVED] entries are the user's own best results — lean on them.
- [TECHNIQUE LESSON: positive/...] entries are confirmed preferences — honor them.
- [USER FACT: comfyui_mechanics / runpod_mechanics] entries are user-verified — authoritative.
- [TUTORIAL KNOWLEDGE] entries are useful references but defer to USER FACT on conflicts.

Output STRICT JSON of this exact shape:
{
  "prompt": "the positive prompt",
  "negative_prompt": null or "the negative prompt (only if a negative slot exists)",
  "settings": {"steps": 20, "cfg": 1.0, "sampler": "euler", "scheduler": "simple", "flux_guidance": 3.5},
  "model": "flux1-dev.safetensors" or null,
  "seed_strategy": "fixed" or "random",
  "seed": 42 or null,
  "width": 1024,
  "height": 1024,
  "lora_stack": [{"name": "char-lora.safetensors", "strength": 0.8}],
  "rationale": "one or two sentences on the key choices, citing retrieved lessons when relevant"
}
Output JSON only.
"""

_RETRY_SUFFIX = (
    "\n\nIMPORTANT: your previous response was not valid JSON of the required shape. "
    "Reproduce your full JSON response exactly as specified (prompt, negative_prompt, "
    "settings, model, seed_strategy, seed, width, height, lora_stack, rationale). Output JSON only."
)


class DraftParseError(ValueError):
    """Raised when the craft response can't be parsed into a spec."""


def _record_llm(model: str, input_tokens: int, output_tokens: int) -> None:
    """Route LLM cost through the active BudgetTracker when present, else emit directly."""
    from agent_runtime.budget import get_current_tracker

    tracker = get_current_tracker()
    if tracker is not None:
        tracker.add_llm_cost(model, input_tokens, output_tokens)
    else:
        record_llm_call(model, input_tokens, output_tokens, 0.0)


def _format_models(models: list[ModelAsset]) -> str:
    if not models:
        return "(none registered — set model to null and describe the desired model)"
    lines = []
    for m in models:
        flag = " [identity-bearing]" if m.identity_bearing else ""
        base = f", base={m.base_model}" if m.base_model else ""
        lines.append(f"- {m.name} ({m.kind}{base}){flag}")
    return "\n".join(lines)


def _build_user_message(
    intent: str,
    ctx: RetrievedContext,
    template: WorkflowTemplate | None,
    models: list[ModelAsset],
) -> str:
    context_block = build_context_prompt(ctx) if not ctx.is_empty() else "(no prior context)"
    if template is not None:
        slots = ", ".join(sorted(template.slot_map.keys())) or "(none)"
        template_block = (
            f"Template: {template.name}\nAvailable slots: {slots}\n"
            f"Required models: {', '.join(template.required_models) or '(none)'}"
        )
    else:
        template_block = "Template: (none chosen — propose generic settings; no slot constraints)"

    return f"""Creative intent:
{intent}

{template_block}

Available models (pick model/LoRA names from these):
{_format_models(models)}

Relevant context:
{context_block}

Craft one settled generation spec for this intent."""


async def craft_spec(
    intent: str,
    ctx: RetrievedContext,
    template: WorkflowTemplate | None,
    models: list[ModelAsset],
    client: AsyncAnthropic,
) -> dict:
    """Run the craft chain once (retry once on a parse failure), returning the spec dict."""
    user_message = _build_user_message(intent, ctx, template, models)
    valid_model_names = {m.name for m in models}

    response = await client.messages.create(
        model=MODEL_DIRECTOR,
        max_tokens=MAX_DRAFT_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    _record_llm(MODEL_DIRECTOR, response.usage.input_tokens, response.usage.output_tokens)

    try:
        return _parse_spec_response(response, valid_model_names, template)
    except DraftParseError:
        logger.warning("Craft response unparseable; retrying once with explicit reminder")
        retry = await client.messages.create(
            model=MODEL_DIRECTOR,
            max_tokens=MAX_DRAFT_TOKENS,
            system=_SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": response.content[0].text},
                {"role": "user", "content": _RETRY_SUFFIX},
            ],
        )
        _record_llm(MODEL_DIRECTOR, retry.usage.input_tokens, retry.usage.output_tokens)
        return _parse_spec_response(retry, valid_model_names, template)


def _parse_spec_response(
    response: Message,
    valid_model_names: set[str],
    template: WorkflowTemplate | None,
) -> dict:
    text = response.content[0].text.strip()
    json_match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if json_match:
        text = json_match.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DraftParseError(f"Craft response was not valid JSON: {exc}") from exc

    if not isinstance(data, dict) or not data.get("prompt"):
        raise DraftParseError("Craft response missing a `prompt`")

    settings = data.get("settings") or {}
    if not isinstance(settings, dict):
        settings = {}

    # A model name is honored only if it exists in the registry (empty registry → null).
    model = data.get("model")
    if model is not None and valid_model_names and model not in valid_model_names:
        model = None

    lora_stack = []
    for lr in data.get("lora_stack") or []:
        if isinstance(lr, dict) and lr.get("name"):
            if not valid_model_names or lr["name"] in valid_model_names:
                lora_stack.append({"name": lr["name"], "strength": lr.get("strength", 1.0)})

    # Defensive: drop a negative the template can't use (keeps the spec honest).
    negative = data.get("negative_prompt")
    if template is not None and "negative" not in template.slot_map:
        negative = None

    return {
        "prompt": data["prompt"],
        "negative_prompt": negative,
        "settings": settings,
        "model": model,
        "seed_strategy": data.get("seed_strategy") or "fixed",
        "seed": data.get("seed"),
        "width": data.get("width"),
        "height": data.get("height"),
        "lora_stack": lora_stack,
        "rationale": data.get("rationale", ""),
    }
