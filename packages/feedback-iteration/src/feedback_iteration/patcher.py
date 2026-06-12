"""Surgical in-place patching — pure string splice, never a re-render.

A revision is a set of `Replace(span, new_text)` ops over the *original* brief
text. `apply_patches` splices them right-to-left so earlier offsets stay valid;
every byte outside a replaced span is preserved exactly. That is the mechanism
by which the director's hand-edits, checked boxes, and deleted steps elsewhere
survive a revision untouched.

Timestamp tokens embedded in downstream step prose are retimed by a BOUNDED,
value-scoped substitution: only the specific changed boundary values from the
time engine's `boundary_subs` are rewritten (matched as whole `N.NNNs` tokens),
so the 0.500s gap token and unchanged intra-clip `duration =` tokens are never
touched.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from feedback_iteration.models import SectionBlock, Span, StepLine


@dataclass
class Replace:
    span: Span
    new_text: str


def apply_patches(text: str, patches: list[Replace]) -> str:
    """Apply disjoint replacements to `text`. Right-to-left so offsets hold."""
    ordered = sorted(patches, key=lambda p: p.span.start, reverse=True)
    prev_start: int | None = None
    for p in ordered:
        if prev_start is not None and p.span.end > prev_start:
            raise ValueError(
                f"overlapping patch spans: {p.span} overlaps a later span starting at {prev_start}"
            )
        prev_start = p.span.start
    out = text
    for p in ordered:
        out = out[: p.span.start] + p.new_text + out[p.span.end :]
    return out


def rewrite_step_text(step: StepLine, new_text: str) -> Replace:
    return Replace(step.text_span, new_text)


def set_checkbox(step: StepLine, checked: bool) -> Replace:
    return Replace(step.checkbox_span, "[x]" if checked else "[ ]")


def replace_timeline_cells(row_start_span: Span, row_end_span: Span, start_text: str, end_text: str) -> list[Replace]:
    return [Replace(row_start_span, start_text), Replace(row_end_span, end_text)]


def replace_heading_timespan(section: SectionBlock, start_text: str, end_text: str) -> Replace:
    if section.heading_timespan is None:
        raise ValueError(f"section '{section.section_id}' heading has no time span to replace")
    return Replace(section.heading_timespan, f" — {start_text} → {end_text}")


def insert_step(steps_region_end: int, line_text: str) -> Replace:
    """Append a new step line after the section's last step (zero-width insert)."""
    return Replace(Span(steps_region_end, steps_region_end), "\n" + line_text)


def _prose_token(value: float) -> str:
    return f"{value:.3f}s"


def _sub_pattern(boundary_subs: list[tuple[float, float]]):
    mapping = {_prose_token(old): _prose_token(new) for old, new in boundary_subs if old != new}
    if not mapping:
        return None, mapping
    pattern = re.compile(r"(?<![\d.])(" + "|".join(re.escape(tok) for tok in mapping) + r")")
    return pattern, mapping


def retime_text(text: str, boundary_subs: list[tuple[float, float]]) -> str:
    """Retime changed boundary tokens in a raw string (used for an LLM step
    rewrite whose section also moved in the cascade — the rewrite was authored
    against the pre-cascade numbers)."""
    pattern, mapping = _sub_pattern(boundary_subs)
    if pattern is None:
        return text
    return pattern.sub(lambda m: mapping[m.group(1)], text)


def substitute_prose_boundaries(
    section: SectionBlock, boundary_subs: list[tuple[float, float]], *, skip_spans: set[int] | None = None
) -> list[Replace]:
    """Retime changed boundary tokens inside this section's step + notation prose.

    Only the exact `N.NNNs` tokens whose value actually changed are rewritten,
    matched as whole numeric tokens (a leading digit/dot guard prevents matching
    inside a longer number). `skip_spans` excludes lines a manual rewrite already
    owns. Returns one Replace per line whose body changed.
    """
    pattern, mapping = _sub_pattern(boundary_subs)
    if pattern is None:
        return []
    skip = skip_spans or set()

    patches: list[Replace] = []
    # Steps and notations both embed timestamps; retime both so a shifted
    # section stays internally consistent. The "> ⚠ " prefix has no token, so
    # operating on the notation body span preserves it.
    for line in (*section.steps, *section.notations):
        if line.text_span.start in skip:
            continue
        new_body = pattern.sub(lambda m: mapping[m.group(1)], line.text)
        if new_body != line.text:
            patches.append(Replace(line.text_span, new_body))
    return patches
