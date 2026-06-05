from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _fake_voice(voice_id, name, category, labels=None, description=None) -> SimpleNamespace:
    return SimpleNamespace(
        voice_id=voice_id,
        name=name,
        category=category,
        labels=labels,
        description=description,
    )


def _patched_client(voices=None, subscription=None, tts_chunks=None):
    """Patch AsyncElevenLabs so constructing ElevenLabsClient yields a mock SDK."""
    sdk = MagicMock()
    sdk.voices.get_all = AsyncMock(return_value=SimpleNamespace(voices=voices or []))
    sdk.user.subscription.get = AsyncMock(return_value=subscription)

    async def _aiter(chunks):
        for c in chunks:
            yield c

    # convert() is a plain (non-async) call returning an async iterator of bytes.
    sdk.text_to_speech.convert = MagicMock(return_value=_aiter(tts_chunks or [b""]))
    return patch(
        "voiceover_direction.elevenlabs_client.AsyncElevenLabs",
        return_value=sdk,
    )


def test_missing_key_raises() -> None:
    # Hermetic: stub config to a keyless state rather than deleting the env var, which a
    # local .env would silently re-supply (pydantic-settings reads the file too).
    from voiceover_direction.elevenlabs_client import ElevenLabsClient

    keyless = SimpleNamespace(elevenlabs_api_key=None)
    with patch("voiceover_direction.elevenlabs_client.get_config", return_value=keyless):
        with pytest.raises(ValueError, match="ELEVENLABS_API_KEY"):
            ElevenLabsClient()


@pytest.mark.asyncio
async def test_list_voices_maps_category_and_passes_labels() -> None:
    voices = [
        _fake_voice("v1", "Rachel", "premade", labels={"accent": "american"}, description="calm"),
        _fake_voice("v2", "MyClone", "cloned", labels={"accent": "british"}),
        _fake_voice("v3", "Pro", "professional"),
    ]
    with _patched_client(voices=voices):
        from voiceover_direction.elevenlabs_client import ElevenLabsClient

        profiles = await ElevenLabsClient().list_voices()

    by_id = {p.voice_id: p for p in profiles}
    assert by_id["v1"].category == "stock"  # premade -> stock
    assert by_id["v1"].labels == {"accent": "american"}
    assert by_id["v1"].description == "calm"
    assert by_id["v2"].category == "cloned"  # cloned -> cloned
    assert by_id["v3"].category == "cloned"  # professional -> cloned
    assert by_id["v2"].description is None


@pytest.mark.asyncio
async def test_list_voices_handles_missing_labels() -> None:
    voices = [_fake_voice("v1", "Rachel", "premade", labels=None)]
    with _patched_client(voices=voices):
        from voiceover_direction.elevenlabs_client import ElevenLabsClient

        profiles = await ElevenLabsClient().list_voices()
    assert profiles[0].labels == {}


@pytest.mark.asyncio
async def test_get_usage_computes_remaining() -> None:
    sub = SimpleNamespace(
        character_count=1500,
        character_limit=10000,
        next_character_count_reset_unix=1719792000,
    )
    with _patched_client(subscription=sub):
        from voiceover_direction.elevenlabs_client import ElevenLabsClient

        usage = await ElevenLabsClient().get_usage()

    assert usage.character_count == 1500
    assert usage.character_limit == 10000
    assert usage.characters_remaining == 8500
    assert usage.next_reset_unix == 1719792000


@pytest.mark.asyncio
async def test_get_usage_tolerates_missing_reset_field() -> None:
    sub = SimpleNamespace(character_count=0, character_limit=5000)
    with _patched_client(subscription=sub):
        from voiceover_direction.elevenlabs_client import ElevenLabsClient

        usage = await ElevenLabsClient().get_usage()
    assert usage.characters_remaining == 5000
    assert usage.next_reset_unix is None


@pytest.mark.asyncio
async def test_synthesize_joins_chunks_and_saves(tmp_path) -> None:
    chunks = [b"RIFF", b"audio", b"data"]
    with _patched_client(tts_chunks=chunks) as ctor:
        from voiceover_direction.elevenlabs_client import ElevenLabsClient

        client = ElevenLabsClient()
        audio = await client.synthesize("[whispers] hello", "voice-1", model_id="eleven_v3")

    assert audio == b"RIFFaudiodata"
    out = tmp_path / "speech.mp3"
    out.write_bytes(audio)
    assert out.read_bytes() == b"RIFFaudiodata"

    # The SDK convert() was called with the directed text + voice + model.
    sdk = ctor.return_value
    kwargs = sdk.text_to_speech.convert.call_args.kwargs
    assert kwargs["text"] == "[whispers] hello"
    assert kwargs["voice_id"] == "voice-1"
    assert kwargs["model_id"] == "eleven_v3"


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("creative", 0.0), ("natural", 0.5), ("robust", 1.0), ("Creative", 0.0), ("ROBUST", 1.0)],
)
@pytest.mark.asyncio
async def test_synthesize_maps_v3_stability_mode_to_float(mode: str, expected: float) -> None:
    # eleven_v3 stability is a discrete mode; the API wants the float. Map it at the boundary.
    with _patched_client(tts_chunks=[b"x"]) as ctor:
        from voiceover_direction.elevenlabs_client import ElevenLabsClient

        await ElevenLabsClient().synthesize(
            "hi", "v1", voice_settings={"stability": mode, "similarity_boost": 0.75}
        )
    kwargs = ctor.return_value.text_to_speech.convert.call_args.kwargs
    assert kwargs["voice_settings"] == {"stability": expected, "similarity_boost": 0.75}


@pytest.mark.asyncio
async def test_synthesize_passes_numeric_stability_through() -> None:
    # v2-style float settings stay valid — only string modes are translated.
    with _patched_client(tts_chunks=[b"x"]) as ctor:
        from voiceover_direction.elevenlabs_client import ElevenLabsClient

        await ElevenLabsClient().synthesize(
            "hi", "v1", voice_settings={"stability": 0.3, "style": 0.0}
        )
    kwargs = ctor.return_value.text_to_speech.convert.call_args.kwargs
    assert kwargs["voice_settings"] == {"stability": 0.3, "style": 0.0}


@pytest.mark.asyncio
async def test_synthesize_unknown_stability_mode_raises() -> None:
    with _patched_client(tts_chunks=[b"x"]):
        from voiceover_direction.elevenlabs_client import ElevenLabsClient

        with pytest.raises(ValueError, match="creative, natural, robust"):
            await ElevenLabsClient().synthesize(
                "hi", "v1", voice_settings={"stability": "wild"}
            )


@pytest.mark.asyncio
async def test_synthesize_omits_voice_settings_when_empty() -> None:
    with _patched_client(tts_chunks=[b"x"]) as ctor:
        from voiceover_direction.elevenlabs_client import ElevenLabsClient

        await ElevenLabsClient().synthesize("hi", "v1", voice_settings=None)
    kwargs = ctor.return_value.text_to_speech.convert.call_args.kwargs
    assert "voice_settings" not in kwargs
