from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import NoTranscriptFound, TranscriptsDisabled


def fetch_youtube_captions(youtube_url: str) -> tuple[str, str] | None:
    """Return (plain_text, timed_text) or None if captions are unavailable.

    plain_text: clean concatenated transcript for cleanup/summary chains
    timed_text: one line per segment with [MM:SS] prefix for timestamp chain
    """
    try:
        video_id = extract_video_id(youtube_url)
        transcript = YouTubeTranscriptApi().fetch(video_id)
        plain = " ".join(s.text for s in transcript)
        timed = "\n".join(f"[{_fmt_seconds(s.start)}] {s.text}" for s in transcript)
        return plain, timed
    except (TranscriptsDisabled, NoTranscriptFound):
        return None


def extract_video_id(youtube_url: str) -> str:
    """Extract YouTube video ID from any standard URL format."""
    parsed = urlparse(youtube_url)
    if parsed.netloc in ("youtu.be",):
        return parsed.path.lstrip("/")
    qs = parse_qs(parsed.query)
    ids = qs.get("v", [])
    if not ids:
        raise ValueError(f"Could not extract video ID from URL: {youtube_url}")
    return ids[0]


def _fmt_seconds(s: float) -> str:
    m, sec = divmod(int(s), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"
