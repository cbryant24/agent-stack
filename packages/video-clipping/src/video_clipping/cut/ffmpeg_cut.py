"""ffmpeg cut for one clip: stream copy first, re-encode fallback.

Silent-source handling: if the source has no audio track, the re-encode
fallback uses `-an` (drop audio); otherwise `-c:a copy` on the fallback so
we don't needlessly re-encode a good audio track. The audio probe is cached
per video via `has_audio_stream(..., cache)`.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from agent_runtime.tracing.decorators import record_tool_call

from video_clipping.exceptions import CutError, FfprobeError
from video_clipping.models import ClipDecision


def has_audio_stream(video: Path, cache: dict[Path, bool] | None = None) -> bool:
    """True iff ffprobe reports ≥1 stream with codec_type=audio.

    Pass `cache` (a dict keyed by video path) to memoize across many clips
    from the same source.
    """
    resolved = video.resolve()
    if cache is not None and resolved in cache:
        return cache[resolved]
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "a",
        "-show_entries", "stream=codec_type",
        "-of", "json", str(video),
    ]
    try:
        proc = subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        raise FfprobeError(
            f"ffprobe failed for {video}: {exc.stderr.decode(errors='replace').strip()}"
        ) from exc
    try:
        streams = json.loads(proc.stdout.decode()).get("streams", [])
    except json.JSONDecodeError as exc:
        raise FfprobeError(f"ffprobe returned non-JSON for {video}: {exc}") from exc
    result = any(s.get("codec_type") == "audio" for s in streams)
    if cache is not None:
        cache[resolved] = result
    return result


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: str, max_len: int = 60) -> str:
    lowered = text.lower()
    hyphenated = _SLUG_RE.sub("-", lowered).strip("-")
    if not hyphenated:
        return "clip"
    return hyphenated[:max_len].rstrip("-") or "clip"


def cut_clip(
    video: Path,
    decision: ClipDecision,
    order_index: int,
    clips_dir: Path,
    audio_cache: dict[Path, bool] | None = None,
) -> Path:
    clips_dir.mkdir(parents=True, exist_ok=True)
    name = f"{order_index:02d}_{_slug(decision.one_line_summary)}.mp4"
    out = clips_dir / name

    ss = f"{decision.refined_start:.3f}"
    to = f"{decision.refined_end:.3f}"

    base = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", ss, "-to", to, "-i", str(video),
    ]

    # Try 1: stream copy (fast, lossless; may fail at non-keyframe boundaries).
    copy_cmd = base + ["-c", "copy", str(out)]
    copy_proc = subprocess.run(copy_cmd, capture_output=True)
    if copy_proc.returncode == 0 and out.exists() and out.stat().st_size > 0:
        record_tool_call(
            "ffmpeg.cut",
            f"segment={decision.segment_id} mode=copy",
            f"out={out.name} bytes={out.stat().st_size}",
        )
        return out

    # Try 2: re-encode. Copy audio if present, else drop.
    audio_flags: list[str]
    if has_audio_stream(video, cache=audio_cache):
        audio_flags = ["-c:a", "copy"]
    else:
        audio_flags = ["-an"]
    reenc_cmd = base + [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        *audio_flags,
        str(out),
    ]
    reenc_proc = subprocess.run(reenc_cmd, capture_output=True)
    if reenc_proc.returncode == 0 and out.exists() and out.stat().st_size > 0:
        record_tool_call(
            "ffmpeg.cut",
            f"segment={decision.segment_id} mode=reencode audio={'copy' if audio_flags[0] == '-c:a' else 'none'}",
            f"out={out.name} bytes={out.stat().st_size}",
        )
        return out

    raise CutError(
        f"ffmpeg cut failed for {decision.segment_id}: "
        f"copy_stderr={copy_proc.stderr.decode(errors='replace').strip()[:200]!r} "
        f"reencode_stderr={reenc_proc.stderr.decode(errors='replace').strip()[:200]!r}"
    )
