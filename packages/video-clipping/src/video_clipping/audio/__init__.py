"""Stage 2 — transcription (faster-whisper, local).

Do not re-export `transcribe` (the function) from this package init: that would
shadow the `video_clipping.audio.transcribe` module and break attribute-style
monkeypatching in tests. Callers import from the submodules directly:

    from video_clipping.audio.transcribe import transcribe
    from video_clipping.audio.slice import slice_transcript
"""

from __future__ import annotations
