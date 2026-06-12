"""Assemble + render the director-owned `edit-brief.md`.

The brief carries frontmatter (project_id, version, discovered-input
provenance), stable section anchors derived from the script's H1 slugs, the
three layers (timeline skeleton, beat grid, per-section checkbox steps), and
every missing-input notation the discovered inputs dictate. Written next to the
script; the vault gets only the standard run report.
"""
from __future__ import annotations

from edit_brief.models import (
    BeatGrid,
    DiscoveredInputs,
    EditBrief,
    SectionSteps,
    TimelineRow,
    now_date,
)
from edit_brief.retrieval import RetrievedContext


def build_structural_notations(
    inputs: DiscoveredInputs,
    timeline: list[TimelineRow],
    beat_grid: BeatGrid | None,
    ctx: RetrievedContext,
) -> list[str]:
    """The brief-level missing-input notations — computed in code, not the LLM.
    Each absence is named explicitly with the upstream agent to run."""
    notes: list[str] = []

    estimated = [r.section_id for r in timeline if r.timing_source == "estimate"]
    if estimated:
        if len(estimated) == len(timeline):
            notes.append(
                "No voiceover takes discovered for this project — ALL section "
                "timestamps are word-count ESTIMATES, not measured durations. Run "
                "`voiceover-direction` and regenerate the brief for exact timing."
            )
        else:
            notes.append(
                "Some sections have no VO take — their timestamps are estimates: "
                + ", ".join(estimated)
            )

    if not inputs.has_music:
        notes.append("No music track provided (`--music FILE`) — no track on the timeline.")
    if beat_grid is None:
        notes.append(
            "No BPM available — beat grid omitted. Pass `--bpm N`, or log the track "
            "in music-curation, to get beat-aligned cut proposals."
        )
    elif inputs.music.bpm_source == "matched":
        notes.append(
            f"BPM {inputs.music.bpm} is a PROPOSAL matched from music-curation"
            + (f" (track \"{inputs.music.matched_title}\")" if inputs.music.matched_title else "")
            + " — confirm it matches your actual track, or override with `--bpm`."
        )

    if not ctx.has_findings:
        notes.append(
            "No technique findings retrieved — steps are grounded only in the "
            "editing toolset. Run `technique-research` for technique-specific guidance."
        )

    if not inputs.has_assets:
        notes.append("No generated assets or `--footage` discovered — footage sourcing is unaddressed.")

    ambiguous = [t.section_id for t in inputs.vo_takes if t.ambiguous]
    if ambiguous:
        notes.append(
            "Multiple positively-reacted VO takes exist for: "
            + ", ".join(ambiguous)
            + " — the latest was used; verify the intended take."
        )

    return notes


def assemble_brief(
    project_id: str,
    source_path: str | None,
    inputs: DiscoveredInputs,
    timeline: list[TimelineRow],
    beat_grid: BeatGrid | None,
    sections: list[SectionSteps],
    ctx: RetrievedContext,
    overall_notations: list[str],
) -> EditBrief:
    structural = build_structural_notations(inputs, timeline, beat_grid, ctx)
    return EditBrief(
        project_id=project_id,
        version=1,
        provenance=inputs,
        timeline=timeline,
        beat_grid=beat_grid,
        sections=sections,
        notations=structural + overall_notations,
        source_path=source_path,
    )


def _fmt(sec: float) -> str:
    m, s = divmod(sec, 60)
    return f"{int(m):02d}:{s:06.3f}"  # mm:ss.mmm — human-scannable on the timeline


def render_brief(brief: EditBrief) -> str:
    lines: list[str] = []

    # ── Frontmatter (provenance) ──────────────────────────────────────────────
    m = brief.provenance.music
    lines += [
        "---",
        f"project_id: {brief.project_id}",
        f"version: {brief.version}",
        f"date: {now_date()}",
        "agent: edit-brief",
        "inputs:",
        f"  vo_takes: {sum(1 for t in brief.provenance.vo_takes if t.duration_sec is not None)} "
        f"of {len(brief.timeline)} sections",
        f"  music_file: {m.file or 'none'}",
        f"  music_duration_sec: {m.duration_sec if m.duration_sec is not None else 'none'}",
        f"  bpm: {m.bpm if m.bpm is not None else 'none'} ({m.bpm_source})",
        f"  assets: {len(brief.provenance.assets)}",
        "---",
        "",
        f"# Edit Brief — {brief.project_id}",
        "",
    ]

    if brief.notations:
        lines += ["> **Missing inputs / notes**", ""]
        lines += [f"> - {n}" for n in brief.notations]
        lines.append("")

    # ── Layer 1: timeline skeleton ────────────────────────────────────────────
    lines += ["## Timeline", "", "| Section | Start | End | VO | Timing |", "|---|---|---|---|---|"]
    for r in brief.timeline:
        anchor = f"[{r.heading}](#{r.section_id})"
        vo = r.vo_file or "—"
        lines.append(
            f"| {anchor} | {_fmt(r.start_sec)} | {_fmt(r.end_sec)} | {vo} | {r.timing_source} |"
        )
    lines.append("")

    # ── Layer 2: beat grid ────────────────────────────────────────────────────
    lines += ["## Beat grid", ""]
    bg = brief.beat_grid
    if bg is None:
        lines += ["_No beat grid — no BPM available. See missing-inputs above._", ""]
    else:
        lines.append(
            f"BPM **{bg.bpm}** · beat {bg.beat_sec:.3f}s · bar {bg.bar_sec:.3f}s. "
            "Nearest-beat alignments are **proposals** — you choose where boundaries land."
        )
        lines += ["", "| Section boundary | Computed | Nearest beat | Nearest bar |", "|---|---|---|---|"]
        for bp in bg.boundary_proposals:
            lines.append(
                f"| {bp.section_id} | {_fmt(bp.boundary_sec)} | {_fmt(bp.nearest_beat_sec)} "
                f"| {_fmt(bp.nearest_bar_sec)} |"
            )
        if bg.note:
            lines += ["", f"_{bg.note}_"]
        lines.append("")

    # ── Layer 3: per-section ordered steps ────────────────────────────────────
    lines += ["## Sections", ""]
    row_by_id = {r.section_id: r for r in brief.timeline}
    for s in brief.sections:
        row = row_by_id.get(s.section_id)
        span = f" — {_fmt(row.start_sec)} → {_fmt(row.end_sec)}" if row else ""
        # Explicit HTML anchor so the timeline links resolve regardless of the
        # renderer's heading-slug rules — the stable anchor F&I references.
        lines += [f'<a id="{s.section_id}"></a>', f"### {s.heading}{span}", ""]
        if s.steps:
            lines += [f"- [ ] {step}" for step in s.steps]
        else:
            lines.append("_No steps generated for this section._")
        if s.notations:
            lines.append("")
            lines += [f"> ⚠ {n}" for n in s.notations]
        lines.append("")

    return "\n".join(lines)
