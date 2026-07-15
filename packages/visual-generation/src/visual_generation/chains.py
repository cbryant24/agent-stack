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
from typing import TYPE_CHECKING

from agent_runtime.llm import LLMProvider
from agent_runtime.tracing import record_llm_call

from visual_generation.constants import MAX_DRAFT_TOKENS
from visual_generation.models import ModelAsset, VisualGeneration, WorkflowTemplate
from visual_generation.retrieval import RetrievedContext, build_context_prompt

if TYPE_CHECKING:
    from visual_generation.canon import CanonSubject

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
- [PROJECT CANON: domain] entries are authoritative identity context. Keep any appearance
  language consistent with them rather than inventing your own; identity is primarily
  carried at the model level (character LoRAs / reference assets), so favor placing and
  posing the subject over describing it.
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

_EDIT_MODE_SYSTEM = """\

EDIT MODE — this intent REFINES an existing image (img2img / inpaint), it does not
create one from scratch. Preserve the source's style, medium, and composition; change
ONLY what the intent asks for — this is an EDIT, not a rewrite. The recipe is fixed by
the template and the denoise by the caller: do NOT author settings and do NOT cite
recipe or denoise numbers in your rationale.
"""

_REVISE_MODE_SYSTEM = """\

REVISE MODE — you are revising an existing TEXT-TO-IMAGE prompt, not creating one from
scratch and not editing pixels. Apply ONLY the targeted change the user asks for. Preserve
all unchanged composition/style/lighting and character language VERBATIM
— copy it through word-for-word; do not paraphrase, reorder, or "improve" it. The recipe
(seed, sampler, steps, model, LoRAs, dimensions) is inherited from the parent and locked by
the caller: do NOT author settings and do NOT cite seed/recipe numbers in your rationale.
Output the same JSON spec shape.
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


def _format_cast(cast: list[CanonSubject]) -> str:
    """One line per canon subject the scene features: primary name, other plain aliases,
    and the asset-reference id when set. Never appearance prose — identity is carried at
    the model/asset level, not by descriptors."""
    lines: list[str] = []
    for s in cast:
        others = [a for a in s.aliases[1:] if not a.startswith("@")]
        also = f" (also called: {', '.join(others)})" if others else ""
        asset = f" [asset: {s.id}]" if s.id else ""
        lines.append(f'- "{s.aliases[0]}"{also}{asset}')
    return "\n".join(lines)


def _cast_block(cast: list[CanonSubject] | None) -> str:
    """Composition-time canon: instruct the model to render the scene's canon characters
    by name (so `canon_loras_for` then matches the alias and pins each LoRA). Empty when
    the scene names no canon subject."""
    if not cast:
        return ""
    return (
        "\nProject canon — characters this scene features. Render EACH of them by name, "
        "present and recognizable in the shot; do not omit them. Character identity is "
        "carried at the model level (character LoRAs / reference assets), not by prompt "
        "prose — name and place/pose each character; do not invent detailed physical "
        "descriptions for them:\n" + _format_cast(cast) + "\n"
    )


def _build_user_message(
    intent: str,
    ctx: RetrievedContext,
    template: WorkflowTemplate | None,
    models: list[ModelAsset],
    parent: VisualGeneration | None = None,
    revise: bool = False,
    cast: list[CanonSubject] | None = None,
) -> str:
    context_block = build_context_prompt(ctx) if not ctx.is_empty() else "(no prior context)"
    cast_block = _cast_block(cast)
    if template is not None:
        slots = ", ".join(sorted(template.slot_map.keys())) or "(none)"
        template_block = (
            f"Template: {template.name}\nAvailable slots: {slots}\n"
            f"Required models: {', '.join(template.required_models) or '(none)'}"
        )
    else:
        template_block = "Template: (none chosen — propose generic settings; no slot constraints)"

    if revise and parent is not None:
        # Prose-only text2img revise: anchor on the parent's full prose and fold in the
        # director's own action note (`notes`) and reasoning (`context`) from `report` as
        # the directed-change context. The recipe is inherited + locked by the caller.
        directed = ""
        if parent.notes:
            directed += f"\nDirector's note on the parent (what to change next time): {parent.notes}"
        if parent.context:
            directed += f"\nWhy the director reacted to the parent as they did: {parent.context}"
        return f"""Current text2img prompt (revise this):
{parent.prompt}

Apply ONLY this change: {intent}
{directed}

Preserve all unchanged composition/style/lighting and character language VERBATIM
— this is a targeted revise, not a rewrite. Do not author settings or
cite seed/recipe numbers; the recipe is inherited from the parent.

{template_block}

Available models (pick model/LoRA names from these):
{_format_models(models)}

Relevant context:
{context_block}

Craft one settled generation spec that applies this change to the prompt."""

    if parent is not None:
        # Refinement: anchor on the source prompt and frame this as an edit, so Sonnet
        # tweaks rather than rewrites. Settings are enforced by the caller — the model
        # is told not to author them.
        return f"""Source prompt: {parent.prompt}

Apply ONLY this change: {intent}

Preserve the source's style/medium/composition — EDIT, not rewrite. The recipe is
fixed by the template and denoise by the caller; do not author settings or cite
recipe/denoise numbers.

{template_block}

Available models (pick model/LoRA names from these):
{_format_models(models)}

Relevant context:
{context_block}

Craft one settled generation spec that applies this change to the source."""

    return f"""Creative intent:
{intent}
{cast_block}
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
    provider: LLMProvider,
    *,
    parent: VisualGeneration | None = None,
    refinement: bool = False,
    revise: bool = False,
    model: str | None = None,
    cast: list[CanonSubject] | None = None,
) -> dict:
    """Run the craft chain once (retry once on a parse failure), returning the spec dict.

    `provider` is the pluggable LLM seam (Claude by default; any provider via
    `--provider`). `model` is a `--model` alias (or concrete id, or None for the
    provider's default); the provider resolves it, and the concrete id it reports is
    used for cost attribution.

    On a `refinement` the chain is framed as an img2img/inpaint EDIT and the parsed spec
    is reconciled to the source (recipe stripped; model/LoRAs/dimensions inherited).

    On a `revise` (mutually exclusive with refinement) the chain is framed as a prose-only
    TEXT2IMG revise and the parsed spec inherits the parent's full recipe — seed (as a
    fixed seed), settings, model, LoRAs, and dimensions — so only the prompt changes and
    continuity cannot drift."""
    # Build the effective system + user message ONCE so the parse-retry reuses the
    # identical framing instead of falling back to the txt2img prompts.
    if refinement:
        system = _SYSTEM_PROMPT + _EDIT_MODE_SYSTEM
    elif revise:
        system = _SYSTEM_PROMPT + _REVISE_MODE_SYSTEM
    else:
        system = _SYSTEM_PROMPT
    user_message = _build_user_message(intent, ctx, template, models, parent, revise=revise, cast=cast)
    valid_model_names = {m.name for m in models}
    resolved = provider.resolve_model(model)

    comp = await provider.complete(
        system=system, user_text=user_message, model=resolved, max_tokens=MAX_DRAFT_TOKENS
    )
    _record_llm(comp.model, comp.input_tokens, comp.output_tokens)

    try:
        spec = _parse_spec_response(comp.text, valid_model_names, template)
    except DraftParseError:
        logger.warning("Craft response unparseable; retrying once with explicit reminder")
        # The seam is a single-turn completion: re-call with the reminder appended to the
        # user text (rather than a multi-turn assistant prefill) so it stays provider-neutral.
        retry = await provider.complete(
            system=system,
            user_text=user_message + _RETRY_SUFFIX,
            model=resolved,
            max_tokens=MAX_DRAFT_TOKENS,
        )
        _record_llm(retry.model, retry.input_tokens, retry.output_tokens)
        spec = _parse_spec_response(retry.text, valid_model_names, template)

    if refinement:
        _enforce_refinement(spec, parent)
    elif revise:
        _enforce_revise(spec, parent)
    return spec


def _enforce_refinement(spec: dict, parent: VisualGeneration | None) -> None:
    """Reconcile a crafted spec to its source (mutates in place).

    Strip every recipe knob — the template's recipe stands and the caller owns denoise
    — and, when a parent is present, inherit its identity-bearing attributes
    (model/LoRA stack/dimensions) rather than honoring whatever the model re-guessed.
    The craft's prompt/negative/rationale/seed are kept."""
    spec["settings"] = {}
    if parent is not None:
        spec["model"] = parent.model
        spec["lora_stack"] = [lr.model_dump() for lr in parent.lora_stack]
        spec["width"] = parent.width
        spec["height"] = parent.height


def _enforce_revise(spec: dict, parent: VisualGeneration | None) -> None:
    """Reconcile a revised spec to its parent (mutates in place).

    A prose-only text2img revise: the model authors ONLY the prompt (and negative, subject
    to the template's slot drop-logic). Everything that fixes continuity is inherited from
    the parent — the parent's concrete seed is re-pinned as a FIXED seed (the generation
    record stores the resolved int, not a strategy), and the exact recipe, model, LoRAs,
    and dimensions are carried through so nothing but the prompt can drift."""
    if parent is None:
        return
    spec["seed"] = parent.seed
    spec["seed_strategy"] = "fixed"
    spec["settings"] = dict(parent.settings)
    spec["model"] = parent.model
    spec["lora_stack"] = [lr.model_dump() for lr in parent.lora_stack]
    spec["width"] = parent.width
    spec["height"] = parent.height


def _parse_spec_response(
    text: str,
    valid_model_names: set[str],
    template: WorkflowTemplate | None,
) -> dict:
    text = text.strip()
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
