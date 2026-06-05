from __future__ import annotations

import tempfile
from pathlib import Path

import whisper
import yt_dlp
from agent_runtime.youtube import prepare_ydl_opts

_model: whisper.Whisper | None = None


def _get_model() -> whisper.Whisper:
    global _model
    if _model is None:
        _model = whisper.load_model("small")
    return _model


def transcribe_with_whisper(youtube_url: str) -> tuple[str, str]:
    """Download audio via yt-dlp, transcribe with local Whisper, return (plain, timed)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        audio_path = _download_audio(youtube_url, Path(tmp_dir))
        return _transcribe(audio_path)


def transcribe_from_file(file_path: Path) -> tuple[str, str]:
    """Transcribe a local audio or video file with Whisper, return (plain, timed)."""
    return _transcribe(file_path)


def _transcribe(path: Path) -> tuple[str, str]:
    model = _get_model()
    result = model.transcribe(str(path))
    plain: str = result["text"]
    segments = result.get("segments", [])
    timed = "\n".join(
        f"[{_fmt_seconds(seg['start'])}] {seg['text'].strip()}" for seg in segments
    ) or plain
    return plain, timed


def _download_audio(youtube_url: str, dest_dir: Path) -> Path:
    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(dest_dir / "%(id)s.%(ext)s"),
        "quiet": True,
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
    }
    prepare_ydl_opts(opts)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(youtube_url, download=True)
        video_id = info["id"]
    return next(dest_dir.glob(f"{video_id}.*"))


def _fmt_seconds(s: float) -> str:
    m, sec = divmod(int(s), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"
