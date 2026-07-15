"""Guardrails for LoRA stacks: strength ceilings + stack hygiene.

Advisory-only mitigations for stack-level artifacts. This module mitigates
over-strength and duplicate-checkpoint artifacts; it does NOT provide identity
isolation — no strength value or stack arrangement spatially routes an identity
to one figure in a frame (consolidated audit §6).

1. **Over-strength.** Every LoRA-capable model (SDXL, Flux, SD 1.5, Z-Image, …)
   has a sane strength band (~0.6–1.2). Pushed past a ceiling a LoRA stops being
   an identity/style *hint* and starts *overriding the prompt* — pose, staging,
   and background directions get ignored — while its identity *bleeds* onto every
   figure in the frame (background extras clone the character). The ceiling is
   universal; only the *reason* one is tempted to crank a LoRA that high is
   model-specific (see the Turbo note below).

2. **Same-character duplication.** `draft`'s LLM habitually piles alternate
   checkpoints of one character (e.g. `*-turbo-2500.safetensors`) alongside the
   canon-pinned file; `prune_noncanon_identity` dedupes those against the pin.

3. **Dual-identity stacking (deprecated).** Stacking *different* identity LoRAs
   in one pass is deprecated outright (audit §6): both apply globally to shared
   model activations, so no strength pair isolates them — identities bleed
   across figures. Any stack carrying 2+ identity LoRAs draws an advisory
   pointing at sequential masked single-identity edits instead.

Z-Image-Turbo note (the diagnosis behind the strength guard, carried in the
message text): a character LoRA trained on a *base* model but applied on a
distilled *Turbo* model only registers at ~2.0+ strength — right in the
override/bleed zone. Retraining on the Turbo model (de-distill adapter) makes
it apply near ~1.0 and restores prompt adherence; it does not make
multi-identity frames safe.

Pure functions — no I/O, no registry ownership. Callers pass a strength ceiling
(so a specific model can tighten it) and an `is_identity` predicate (usually
`lambda n: (a := store.get_model(n)) is not None and a.identity_bearing`).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Sequence

from visual_generation.models import LoraRef

# Universal per-entry ceiling: at/above this, a LoRA of any model starts to
# override the prompt and bleed. Overridable globally via env for tuning; a
# caller may pass a lower per-model ceiling (e.g. Z-Image Turbo wants ~1.0).
DEFAULT_STRENGTH_WARN = float(os.environ.get("VG_LORA_STRENGTH_WARN", "1.5"))


def strength_warnings(
    stack: Sequence[LoraRef],
    *,
    ceiling: float = DEFAULT_STRENGTH_WARN,
    is_identity: Callable[[str], bool] | None = None,
) -> list[str]:
    """Advisory warnings for a LoRA stack (warn-loudly-allow — never mutates, never raises).

    Emits one warning per entry at/above `ceiling`, plus one advisory whenever
    the stack carries 2+ identity LoRAs (per `is_identity`; the stacking check
    is skipped when the predicate is None). Returns [] for a sane stack.
    """
    warnings: list[str] = []
    for lr in stack:
        if lr.strength >= ceiling:
            warnings.append(
                f"LoRA '{lr.name}' strength {lr.strength:g} ≥ {ceiling:g}: at this level it overrides "
                f"prompt adherence (pose/staging/background directions get ignored) and its identity "
                f"bleeds onto other figures in the frame. LoRAs are meant to run near ~1.0 — if a "
                f"character LoRA only 'takes' this high, it is probably trained on a base model but run "
                f"on a distilled/Turbo model; retrain it on the Turbo model (de-distill adapter) so it "
                f"applies near 1.0."
            )
    if is_identity is not None:
        identity = [lr for lr in stack if is_identity(lr.name)]
        if len(identity) >= 2:
            names = ", ".join(f"{lr.name}@{lr.strength:g}" for lr in identity)
            warnings.append(
                f"{len(identity)} identity LoRAs stacked ({names}): dual-identity stacking is "
                f"deprecated (audit §6) — no strength pair isolates identities in a single pass; "
                f"identities bleed across figures. Use sequential masked single-identity edits "
                f"(one character per pass)."
            )
    return warnings


def _stem(name: str) -> str:
    return name[: -len(".safetensors")] if name.endswith(".safetensors") else name


def prune_noncanon_identity(
    stack: Iterable[LoraRef],
    canon_pin_names: Iterable[str],
    *,
    is_identity: Callable[[str], bool],
) -> tuple[list[LoraRef], list[str]]:
    """Drop identity LoRAs that duplicate a canon-pinned character (same character,
    different file).

    Scoped deliberately narrow: a non-pin identity LoRA is dropped ONLY when it
    collides with a canon pin — i.e. one of their stems is a prefix of the other,
    so they are the same character in a different file. This catches both the
    alternate-checkpoint case (`narrator-…-turbo-2500` extends the pin stem) and
    the superseded-era case (`narrator-…-coraline` is a prefix of the pinned
    `narrator-…-coraline-turbo`). This is the same-character duplication failure
    mode. Everything else is kept untouched: non-identity adapters, the canon
    pins themselves, and — crucially — identity LoRAs for characters canon does
    NOT pin (a project with no canon, or a legitimately inherited LoRA), since
    with no pin there is no basis to override the choice. Order preserved.
    Returns (kept, notes).
    """
    pins = set(canon_pin_names)
    pin_stems = [_stem(p) for p in pins]
    kept: list[LoraRef] = []
    notes: list[str] = []
    for lr in stack:
        lr_stem = _stem(lr.name)
        collides = any(
            lr_stem.startswith(ps) or ps.startswith(lr_stem) for ps in pin_stems
        )
        if lr.name not in pins and collides and is_identity(lr.name):
            notes.append(
                f"dropped duplicate identity LoRA '{lr.name}'@{lr.strength:g} — canon pins another "
                f"checkpoint of the same character"
            )
            continue
        kept.append(lr)
    return kept, notes
