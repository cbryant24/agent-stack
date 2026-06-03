__version__ = "0.0.1"

from music_curation.agent import curate, curate_sync
from music_curation.models import (
    Generation,
    GenerationRef,
    MusicResult,
    SoundReference,
    SunoPrompt,
    TasteLesson,
    Template,
)

__all__ = [
    "__version__",
    "curate",
    "curate_sync",
    "Generation",
    "GenerationRef",
    "MusicResult",
    "SoundReference",
    "SunoPrompt",
    "TasteLesson",
    "Template",
]
