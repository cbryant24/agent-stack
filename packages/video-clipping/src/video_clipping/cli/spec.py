"""`clip spec init` — scaffold a spec.yaml matching the masterplan schema."""

from __future__ import annotations

from pathlib import Path

import click

_SPEC_TEMPLATE = """\
# video-clipping spec — director's inputs.
# Every `exclude_when` value below matches the masterplan's exclude taxonomy.

video: /absolute/path/to/source.mp4
location: "Yosemite — Half Dome day hike"
event_type: "hike"

# [min_seconds, max_seconds] — segments outside this window are dropped, except
# near-misses within the tolerance band (marked `near_miss_short`/`near_miss_long`).
target_clip_length_sec: [15, 60]

# Total minutes of clips to keep (cap on the highlight reel).
max_total_output_min: 5

content_wanted:
  - "landscape and summit views"
  - "wildlife"
  - "moments with people in frame"

exclude_when:
  - low_video_quality       # from prepass_metrics + vision
  - short_or_long           # outside target_clip_length_sec
  - low_audio_quality       # from loudness/RMS + transcript confidence
  - theme_mismatch          # theme_match < 0.5
  - duplicate_of_previous   # similarity dedupe
  - unidentifiable          # vision confidence low

tone_notes: "keep it calm and observational, not action-highlight-reel"
"""


@click.group("spec")
def spec_group() -> None:
    """Manage spec.yaml files."""


@spec_group.command("init")
@click.option(
    "-o", "--output",
    "output",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path("spec.yaml"),
    show_default=True,
    help="Where to write the scaffolded spec.yaml.",
)
@click.option("--force", is_flag=True, help="Overwrite an existing file.")
def spec_init_command(output: Path, force: bool) -> None:
    """Write a scaffolded spec.yaml with every field populated as a placeholder."""
    if output.exists() and not force:
        raise click.UsageError(f"{output} already exists (use --force to overwrite)")
    output.write_text(_SPEC_TEMPLATE, encoding="utf-8")
    click.echo(f"wrote {output}")
