"""Range validation for a spec, run at plan time (entry-gate item 5).

A value outside its bound is rejected with a plain reason, never clamped: the graph that runs
must carry exactly what the spec and the generation record say. Pure; no I/O.
"""

from __future__ import annotations

from typing import Any

from visual_generation.constants import DEFAULT_DENOISE, SIZE_MULTIPLE, VALUE_BOUNDS
from visual_generation.models import VisualSpec

BOUNDS = VALUE_BOUNDS            # one dict: tuning it (or a test patching it) affects the validator


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _fmt(x: float) -> str:
    if isinstance(x, int):
        return str(x)
    return str(int(x)) if float(x).is_integer() else str(x)


def _between(name: str, value: Any, key: str, *, whole: bool = False) -> str | None:
    lo, hi = BOUNDS[key]
    n = _num(value)
    if n is None:
        return f"{name} must be a number (got {value!r})"
    if whole and not n.is_integer():
        return f"{name} must be a whole number (got {_fmt(n)})"
    # Integers compare exactly: a float would round 2**64 - 1 up to 2**64.
    exact: int | float = value if isinstance(value, int) else n
    if not lo <= exact <= hi:
        return f"{name} must be between {_fmt(lo)} and {_fmt(hi)} (got {_fmt(exact)})"
    return None


def validate_spec(spec: VisualSpec, *, effective: bool = False) -> list[str]:
    """Every out-of-range value in the spec, as plain sentences (empty list = fine).

    `effective=True` checks what will actually run: for a refinement with no denoise set, the
    runtime default (DEFAULT_DENOISE) is part of the settings.
    """
    settings = dict(spec.settings)
    if effective and spec.source is not None and "denoise" not in settings:
        settings["denoise"] = DEFAULT_DENOISE
    problems: list[str] = []

    def add(msg: str | None) -> None:
        if msg:
            problems.append(msg)

    for key in ("cfg", "denoise", "flux_guidance"):
        if key in settings:
            add(_between(key, settings[key], key))
    if "steps" in settings:
        add(_between("steps", settings["steps"], "steps", whole=True))
    if "fps" in settings:
        add(_between("fps", settings["fps"], "fps", whole=True))
    if "length" in settings:
        msg = _between("length", settings["length"], "length", whole=True)
        if msg is None and (int(float(settings["length"])) - 1) % 4 != 0:
            lo, hi = BOUNDS["length"]
            msg = f"length must be 4n+1 between {_fmt(lo)} and {_fmt(hi)} (got {_fmt(float(settings['length']))})"
        add(msg)

    lo, hi = BOUNDS["size"]
    for name, value in (("width", spec.width), ("height", spec.height)):
        if value is None:
            continue
        if not (lo <= value <= hi) or value % SIZE_MULTIPLE != 0:
            problems.append(
                f"{name} must be a multiple of {SIZE_MULTIPLE} between {_fmt(lo)} and {_fmt(hi)} (got {value})"
            )

    for lora in spec.lora_stack:
        add(_between(f"LoRA {lora.name!r} strength", lora.strength, "lora_strength"))

    if spec.seed is not None:
        add(_between("seed", spec.seed, "seed", whole=True))
    return problems
