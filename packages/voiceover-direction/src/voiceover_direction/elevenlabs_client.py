"""ElevenLabs client wrapper.

Covers the read endpoints (list voices, query monthly character usage) and TTS.
The vendor is the source of truth for voices and character usage: nothing queried
here is cached locally, and the monthly character budget never enters
`BudgetEnvelope`. TTS (`synthesize`) is the paid call — spending it is a deliberate
commitment made through `generate` (Step 3), gated by the soft-inform display.
"""

from __future__ import annotations

from agent_runtime import get_config
from elevenlabs.client import AsyncElevenLabs

from voiceover_direction.constants import DEFAULT_MODEL, DEFAULT_OUTPUT_FORMAT
from voiceover_direction.models import CharacterUsage, VoiceProfile


def _normalise_category(vendor_category: str | None) -> str:
    """Collapse ElevenLabs' category field to the registry's stock/cloned split.

    ElevenLabs' built-in library voices are `premade`; everything else
    (`cloned`, `professional`, `generated`, …) is a user/clone voice.
    """
    return "stock" if vendor_category == "premade" else "cloned"


# eleven_v3 expresses stability as a discrete mode, but the API's voice_settings.stability
# is a float (0.0-1.0): lower = broader emotional range, higher = more consistent/monotonous.
# Confirmed against the ElevenLabs Python SDK VoiceSettings docs.
_V3_STABILITY_MODES = {"creative": 0.0, "natural": 0.5, "robust": 1.0}


def _normalise_stability(settings: dict) -> dict:
    """Translate an eleven_v3 stability mode to its API float, at the vendor boundary only.

    The direction chain emits the v3-native mode name (`creative`/`natural`/`robust`) and the
    directed-script `settings` dict carries it; the API rejects the string with a 422. We map
    it here. A numeric stability passes through unchanged (v2-style float settings stay valid —
    the settings dict is model-agnostic). An unknown mode string raises rather than re-trigger
    the opaque 422 or silently mis-map. Returns a new dict; the caller's settings are untouched.
    """
    stability = settings.get("stability")
    if not isinstance(stability, str):
        return settings  # numeric (or absent) — pass through
    mode = stability.strip().lower()
    if mode not in _V3_STABILITY_MODES:
        valid = ", ".join(sorted(_V3_STABILITY_MODES))
        raise ValueError(
            f"Unknown eleven_v3 stability mode {stability!r}; valid modes are: {valid}"
        )
    return {**settings, "stability": _V3_STABILITY_MODES[mode]}


class ElevenLabsClient:
    """Thin async wrapper over the official ElevenLabs SDK (read-only surface)."""

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or get_config().elevenlabs_api_key
        if not key:
            raise ValueError("ELEVENLABS_API_KEY is not configured")
        self._client = AsyncElevenLabs(api_key=key)

    async def list_voices(self) -> list[VoiceProfile]:
        """Return all available voices (stock + cloned) with labels/description."""
        response = await self._client.voices.get_all()
        profiles: list[VoiceProfile] = []
        for voice in response.voices:
            profiles.append(
                VoiceProfile(
                    voice_id=voice.voice_id,
                    name=voice.name,
                    category=_normalise_category(getattr(voice, "category", None)),
                    labels=dict(getattr(voice, "labels", None) or {}),
                    description=getattr(voice, "description", None),
                )
            )
        return profiles

    async def get_usage(self) -> CharacterUsage:
        """Query the monthly character quota. Vendor-reported, never cached."""
        sub = await self._client.user.subscription.get()
        count = sub.character_count
        limit = sub.character_limit
        return CharacterUsage(
            character_count=count,
            character_limit=limit,
            characters_remaining=limit - count,
            next_reset_unix=getattr(sub, "next_character_count_reset_unix", None),
        )

    async def synthesize(
        self,
        text: str,
        voice_id: str,
        *,
        model_id: str = DEFAULT_MODEL,
        output_format: str = DEFAULT_OUTPUT_FORMAT,
        voice_settings: dict | None = None,
    ) -> bytes:
        """Generate speech for `text` and return the full audio as bytes (the paid call).

        `voice_settings` is the model-agnostic settings dict; eleven_v3's expressive control
        is inline audio tags (in the text) plus a discrete stability mode. The only coercion
        applied is `stability`: a v3 mode name is translated to the API's float here at the
        vendor boundary (see `_normalise_stability`); every other key is forwarded as-is.
        """
        if voice_settings:
            voice_settings = _normalise_stability(voice_settings)
        audio = self._client.text_to_speech.convert(
            voice_id=voice_id,
            text=text,
            model_id=model_id,
            output_format=output_format,
            **({"voice_settings": voice_settings} if voice_settings else {}),
        )
        chunks = [chunk async for chunk in audio]
        return b"".join(chunks)
