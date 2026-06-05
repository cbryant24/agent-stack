__version__ = "0.0.1"

from voiceover_direction.agent import direct, direct_sync
from voiceover_direction.directed_script import read_directed_script, write_directed_script
from voiceover_direction.docs_ingest import DocCandidate, ingest_docs, ingest_docs_sync, parse_docs
from voiceover_direction.elevenlabs_client import ElevenLabsClient
from voiceover_direction.generation import (
    GenerationPlan,
    SectionPlan,
    generate,
    generate_sync,
    plan_generation,
    plan_generation_sync,
    spend_generation,
    spend_generation_sync,
)
from voiceover_direction.models import (
    CharacterUsage,
    DirectedScript,
    DirectedSection,
    DirectionLesson,
    DirectionResult,
    GenerationResult,
    ParsedScript,
    ScriptSection,
    Take,
    VoiceoverResult,
    VoiceProfile,
)
from voiceover_direction.parser import parse_script, parse_script_text
from voiceover_direction.retrieval import RetrievedContext, retrieve_context
from voiceover_direction.store import VoiceoverDirectionStore
from voiceover_direction.voice_registry import VoiceRegistry

__all__ = [
    "__version__",
    "CharacterUsage",
    "DocCandidate",
    "DirectedScript",
    "DirectedSection",
    "DirectionLesson",
    "DirectionResult",
    "ElevenLabsClient",
    "GenerationPlan",
    "GenerationResult",
    "ParsedScript",
    "SectionPlan",
    "RetrievedContext",
    "ScriptSection",
    "Take",
    "VoiceRegistry",
    "VoiceoverDirectionStore",
    "VoiceoverResult",
    "VoiceProfile",
    "direct",
    "direct_sync",
    "generate",
    "generate_sync",
    "ingest_docs",
    "ingest_docs_sync",
    "parse_docs",
    "parse_script",
    "plan_generation",
    "plan_generation_sync",
    "spend_generation",
    "spend_generation_sync",
    "parse_script_text",
    "read_directed_script",
    "retrieve_context",
    "write_directed_script",
]
