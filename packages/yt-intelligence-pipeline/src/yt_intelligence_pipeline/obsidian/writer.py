from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from yt_intelligence_pipeline.models import ProcessedOutput, VideoJob
from yt_intelligence_pipeline.utils.slugify import slugify


def write_obsidian_note(vault_path: Path, job: VideoJob, output: ProcessedOutput) -> Path:
    """Assemble and write the note; return its path."""
    slug = slugify(job.video_metadata.title)
    note_path = vault_path / f"{slug}.md"
    note_path.write_text(_build_markdown(job, output, slug), encoding="utf-8")
    return note_path


def _build_markdown(job: VideoJob, output: ProcessedOutput, slug: str) -> str:
    parts = [
        _build_frontmatter(job, output),
        "## Summary\n",
        output.summary,
        "",
        "## Key Takeaways\n",
        *[f"- {t}" for t in output.key_takeaways],
        "",
    ]

    if output.screenshot_timestamps:
        parts.append("## Screenshots\n")
        for i, ts in enumerate(output.screenshot_timestamps, 1):
            filename = f"screenshot_{i:03d}.png"
            parts.append(f"![[{slug}/{filename}]] — {ts.label}")
        parts.append("")

    parts += [
        "## Full Transcript\n",
        output.cleaned_transcript,
        "",
    ]

    return "\n".join(parts)


def _build_frontmatter(job: VideoJob, output: ProcessedOutput) -> str:
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tags_yaml = "\n".join(f"  - {tag}" for tag in output.tags)
    title = job.video_metadata.title.replace('"', '\\"')
    channel = job.video_metadata.channel.replace('"', '\\"')
    return (
        f'---\n'
        f'title: "{title}"\n'
        f'url: {job.youtube_url}\n'
        f'channel: "{channel}"\n'
        f'date_processed: {date_str}\n'
        f'tags:\n{tags_yaml}\n'
        f'---\n\n'
    )
