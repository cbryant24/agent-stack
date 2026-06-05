from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voiceover_direction.chains import direct_script, redirect_section
from voiceover_direction.models import ParsedScript, ScriptSection, Take, VoiceProfile
from voiceover_direction.retrieval import RetrievedContext


class MockMessage:
    def __init__(self, text: str, input_tokens: int = 100, output_tokens: int = 200):
        self.content = [MagicMock(text=text)]
        self.usage = MagicMock(input_tokens=input_tokens, output_tokens=output_tokens)


def _parsed() -> ParsedScript:
    return ParsedScript(
        source_path="s.md",
        sections=[
            ScriptSection(section_id="intro", heading="Intro", body="Welcome back."),
            ScriptSection(section_id="main-point", heading="Main Point", body="Here's the thing."),
        ],
    )


def _voices() -> list[VoiceProfile]:
    return [VoiceProfile(voice_id="voice-1", name="Rachel", category="stock")]


def _response_json(**overrides) -> str:
    data = {
        "sections": [
            {
                "section_id": "intro",
                "directed_text": "[whispers] Welcome back.",
                "voice_id": "voice-1",
                "voice_characteristics": None,
                "model": "eleven_v3",
                "settings": {"stability": "creative"},
                "reasoning": "Soft open.",
            },
            {
                "section_id": "main-point",
                "directed_text": "Here's the thing. [pause]",
                "voice_id": "voice-1",
                "voice_characteristics": None,
                "model": "eleven_v3",
                "settings": {},
                "reasoning": "Land the point.",
            },
        ],
        "overall_reasoning": "Build from soft to assured.",
    }
    data.update(overrides)
    return json.dumps(data)


def _client(*responses: MockMessage) -> MagicMock:
    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(side_effect=list(responses))
    return client


@pytest.mark.asyncio
async def test_parses_per_section_and_maps_headings() -> None:
    client = _client(MockMessage(_response_json()))
    with patch("voiceover_direction.chains.record_llm_call"), \
         patch("agent_runtime.budget.get_current_tracker", return_value=None):
        sections, overall = await direct_script(_parsed(), _voices(), RetrievedContext(), client)

    assert [s.section_id for s in sections] == ["intro", "main-point"]
    assert sections[0].heading == "Intro"  # mapped back from the parsed script
    assert sections[0].text == "[whispers] Welcome back."
    assert sections[0].voice_id == "voice-1"
    assert sections[0].settings == {"stability": "creative"}
    assert overall == "Build from soft to assured."


@pytest.mark.asyncio
async def test_empty_registry_leaves_voice_unset_with_characteristics() -> None:
    resp = _response_json(sections=[{
        "section_id": "intro",
        "directed_text": "[warm] Welcome back.",
        "voice_id": None,
        "voice_characteristics": "calm female narrator",
        "model": "eleven_v3",
        "settings": {},
        "reasoning": "Warm open.",
    }])
    parsed = ParsedScript(sections=[ScriptSection(section_id="intro", heading="Intro", body="Welcome back.")])
    client = _client(MockMessage(resp))
    with patch("voiceover_direction.chains.record_llm_call"), \
         patch("agent_runtime.budget.get_current_tracker", return_value=None):
        sections, _ = await direct_script(parsed, [], RetrievedContext(), client)

    assert sections[0].voice_id is None
    assert "Suggested voice: calm female narrator" in sections[0].notes


@pytest.mark.asyncio
async def test_unknown_voice_id_is_dropped() -> None:
    resp = _response_json(sections=[{
        "section_id": "intro",
        "directed_text": "Hi.",
        "voice_id": "not-in-registry",
        "model": "eleven_v3",
        "settings": {},
        "reasoning": "x",
    }])
    parsed = ParsedScript(sections=[ScriptSection(section_id="intro", heading="Intro", body="Hi.")])
    client = _client(MockMessage(resp))
    with patch("voiceover_direction.chains.record_llm_call"), \
         patch("agent_runtime.budget.get_current_tracker", return_value=None):
        sections, _ = await direct_script(parsed, _voices(), RetrievedContext(), client)
    assert sections[0].voice_id is None


@pytest.mark.asyncio
async def test_bad_json_retries_once_then_succeeds() -> None:
    client = _client(MockMessage("not json at all"), MockMessage(_response_json()))
    with patch("voiceover_direction.chains.record_llm_call"), \
         patch("agent_runtime.budget.get_current_tracker", return_value=None):
        sections, _ = await direct_script(_parsed(), _voices(), RetrievedContext(), client)
    assert client.messages.create.await_count == 2
    assert len(sections) == 2


@pytest.mark.asyncio
async def test_bad_json_twice_raises() -> None:
    from voiceover_direction.chains import DirectionParseError

    client = _client(MockMessage("garbage"), MockMessage("still garbage"))
    with patch("voiceover_direction.chains.record_llm_call"), \
         patch("agent_runtime.budget.get_current_tracker", return_value=None):
        with pytest.raises(DirectionParseError):
            await direct_script(_parsed(), _voices(), RetrievedContext(), client)
    assert client.messages.create.await_count == 2


@pytest.mark.asyncio
async def test_cost_bridged_to_tracker() -> None:
    from agent_runtime import BudgetEnvelope
    from agent_runtime.budget import BudgetTracker

    client = _client(MockMessage(_response_json(), input_tokens=300, output_tokens=150))

    async def run():
        env = BudgetEnvelope(max_items=1, max_depth=0, max_cost_usd=5.0, max_wall_time_sec=300)
        async with BudgetTracker(env, "test-agent") as tracker:
            await direct_script(_parsed(), _voices(), RetrievedContext(), client)
            return tracker._consumption.cost_usd, tracker._consumption.llm_calls

    with patch("agent_runtime.tracing.decorators._emit_to_persister"):
        cost, calls = await run()
    assert cost > 0
    assert calls == 1


# ── redirect_section (option-B fold-in) ──────────────────────────────────────


def _last_take() -> Take:
    return Take(
        text="[warm] Welcome back to the channel.",
        voice_id="voice-1",
        model="eleven_v3",
        section_id="intro",
        project_id="ep",
        reaction="liked_with_changes",
        context="liked the warmth, wanted it slower",
    )


def _redirect_response() -> str:
    return json.dumps({
        "sections": [{
            "section_id": "intro",
            "directed_text": "[warm] [slow] Welcome back to the channel.",
            "voice_id": "voice-1",
            "voice_characteristics": None,
            "model": "eleven_v3",
            "settings": {"stability": "robust"},
            "reasoning": "Slowed the open per the note.",
        }],
        "overall_reasoning": "Addressed the pacing note.",
    })


@pytest.mark.asyncio
async def test_redirect_section_returns_revised_section() -> None:
    client = _client(MockMessage(_redirect_response()))
    with patch("voiceover_direction.chains.record_llm_call"), \
         patch("agent_runtime.budget.get_current_tracker", return_value=None):
        section = await redirect_section(
            _last_take(), "Intro", "slow it down", RetrievedContext(), _voices(), client
        )

    assert section.section_id == "intro"
    assert section.heading == "Intro"
    assert section.text == "[warm] [slow] Welcome back to the channel."
    assert section.settings == {"stability": "robust"}
    assert section.voice_id == "voice-1"


@pytest.mark.asyncio
async def test_redirect_section_bases_on_last_take_text_and_note() -> None:
    # Load-bearing: the base fed to the model is the last take's text + the note.
    client = _client(MockMessage(_redirect_response()))
    with patch("voiceover_direction.chains.record_llm_call"), \
         patch("agent_runtime.budget.get_current_tracker", return_value=None):
        await redirect_section(
            _last_take(), "Intro", "slow it down", RetrievedContext(), _voices(), client
        )

    user_message = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "[warm] Welcome back to the channel." in user_message  # base = last take's text
    assert "slow it down" in user_message  # the note (what to change)
    assert "liked the warmth, wanted it slower" in user_message  # the take's context


@pytest.mark.asyncio
async def test_redirect_section_retries_on_bad_json() -> None:
    client = _client(MockMessage("not json"), MockMessage(_redirect_response()))
    with patch("voiceover_direction.chains.record_llm_call"), \
         patch("agent_runtime.budget.get_current_tracker", return_value=None):
        section = await redirect_section(
            _last_take(), "Intro", "slow it down", RetrievedContext(), _voices(), client
        )
    assert client.messages.create.await_count == 2
    assert section.text == "[warm] [slow] Welcome back to the channel."
