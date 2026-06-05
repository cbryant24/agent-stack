from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_runtime import BudgetEnvelope, get_config

from voiceover_direction.directed_script import write_directed_script
from voiceover_direction.generation import (
    _extract_emotion_tags,
    generate,
    select_sections,
)
from voiceover_direction.models import DirectedScript, DirectedSection, Take
from voiceover_direction.retrieval import RetrievedContext


def _directed_file(tmp_path: Path, *, with_outro_voice: bool = False) -> Path:
    script = DirectedScript(
        project_id="ep-12",
        domain="tech",
        source_path="ep-12.md",
        sections=[
            DirectedSection(
                section_id="intro", heading="Intro",
                text="[whispers] Welcome back. [excited] Let's go.",
                voice_id="voice-1", model="eleven_v3", settings={"stability": "creative"},
            ),
            DirectedSection(
                section_id="outro", heading="Outro", text="Goodbye. [pause]",
                voice_id="voice-2" if with_outro_voice else None, model="eleven_v3",
            ),
        ],
    )
    path = tmp_path / "ep-12.directed.md"
    write_directed_script(script, path)
    return path


def _mock_store(latest=None) -> MagicMock:
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.upsert_take = AsyncMock()
    store.latest_take_for_section = AsyncMock(return_value=latest)
    store.list_voices = MagicMock(return_value=[])
    return store


def _mock_tts() -> MagicMock:
    tts = MagicMock()
    tts.synthesize = AsyncMock(return_value=b"AUDIOBYTES")
    return tts


def _patches():
    return (
        patch("voiceover_direction.generation.render_run_report", return_value=None),
        patch("voiceover_direction.generation.notify_run_complete"),
    )


async def _run(directed_path, **kwargs):
    p1, p2 = _patches()
    with p1, p2:
        return await generate(directed_path, **kwargs)


# ── select_sections / tag extraction ─────────────────────────────────────────


def test_select_sections_errors() -> None:
    script = DirectedScript(project_id="p", sections=[
        DirectedSection(section_id="intro", heading="Intro", text="x"),
    ])
    with pytest.raises(ValueError, match="Unknown section_id"):
        select_sections(script, section_id="nope")
    with pytest.raises(ValueError, match="Specify a section"):
        select_sections(script)


def test_extract_emotion_tags_dedupes_in_order() -> None:
    assert _extract_emotion_tags("[whispers] a [pause] b [whispers] c") == ["[whispers]", "[pause]"]


# ── generate end-to-end ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_writes_pending_take_and_audio(tmp_path: Path) -> None:
    directed = _directed_file(tmp_path)  # intro has a voice, outro does not
    store = _mock_store()
    tts = _mock_tts()

    result = await _run(directed, all_sections=True, usage_remaining=1000, store=store, tts_client=tts)

    assert result.status == "completed"
    assert result.items_processed == 1  # only intro is spendable
    assert result.skipped == ["outro"]

    # Pending take written with correct facts.
    take: Take = store.upsert_take.call_args.args[0]
    assert isinstance(take, Take)
    assert take.status == "pending"
    assert take.reaction == "pending"
    assert take.character_count == len("[whispers] Welcome back. [excited] Let's go.")
    assert take.voice_id == "voice-1"
    assert take.model == "eleven_v3"
    assert take.settings == {"stability": "creative"}
    assert take.emotion_tags == ["[whispers]", "[excited]"]
    assert take.section_id == "intro"
    assert take.project_id == "ep-12"
    assert take.domain == "tech"

    # audio_path on the take is RELATIVE; the file exists at agent_data_dir/<rel>.
    assert not Path(take.audio_path).is_absolute()
    assert take.audio_path.startswith("voiceover/audio/ep-12/")
    abs_audio = get_config().agent_data_dir / take.audio_path
    assert abs_audio.exists()
    assert abs_audio.read_bytes() == b"AUDIOBYTES"

    # VoiceoverResult: absolute path + projected remaining.
    vr = result.results[0]
    assert Path(vr.audio_path).is_absolute()
    assert vr.character_cost == take.character_count
    assert vr.remaining_characters == 1000 - take.character_count


@pytest.mark.asyncio
async def test_first_take_is_a_section_root(tmp_path: Path) -> None:
    directed = _directed_file(tmp_path)
    store = _mock_store(latest=None)  # no prior take in the section
    await _run(directed, section_id="intro", store=store, tts_client=_mock_tts())
    take: Take = store.upsert_take.call_args.args[0]
    assert take.parent_take_id is None
    assert take.chain_root_id == take.entry_id  # root sets chain_root to itself


@pytest.mark.asyncio
async def test_regenerate_parents_off_latest_take(tmp_path: Path) -> None:
    directed = _directed_file(tmp_path)
    prior = Take(text="old", voice_id="voice-1", model="eleven_v3",
                 section_id="intro", project_id="ep-12", chain_root_id="root-x")
    prior.chain_root_id = "root-x"
    store = _mock_store(latest=prior)
    await _run(directed, section_id="intro", store=store, tts_client=_mock_tts())
    take: Take = store.upsert_take.call_args.args[0]
    assert take.parent_take_id == prior.entry_id
    assert take.chain_root_id == "root-x"  # keeps the chain's root


@pytest.mark.asyncio
async def test_no_voice_section_skipped_not_generated(tmp_path: Path) -> None:
    directed = _directed_file(tmp_path)  # outro has no voice
    store = _mock_store()
    tts = _mock_tts()
    result = await _run(directed, section_id="outro", store=store, tts_client=tts)
    assert result.skipped == ["outro"]
    assert result.items_processed == 0
    store.upsert_take.assert_not_called()
    tts.synthesize.assert_not_called()


@pytest.mark.asyncio
async def test_remaining_unknown_when_no_usage(tmp_path: Path) -> None:
    directed = _directed_file(tmp_path)
    result = await _run(directed, section_id="intro", usage_remaining=None,
                        store=_mock_store(), tts_client=_mock_tts())
    assert result.results[0].remaining_characters is None


# ── tracing + budget orthogonality ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_characters_recorded_as_span_attr_not_budget(tmp_path: Path) -> None:
    directed = _directed_file(tmp_path, with_outro_voice=True)  # two spendable sections
    store = _mock_store()
    p1, p2 = _patches()
    with p1, p2, patch("voiceover_direction.generation._record_characters") as rec:
        result = await generate(directed, all_sections=True, store=store, tts_client=_mock_tts())

    # Characters recorded cumulatively as a span attribute.
    intro_chars = len("[whispers] Welcome back. [excited] Let's go.")
    outro_chars = len("Goodbye. [pause]")
    assert [c.args[0] for c in rec.call_args_list] == [intro_chars, intro_chars + outro_chars]

    # Orthogonality: no LLM call → zero Claude cost; characters never became a budget dimension.
    assert result.cost_usd == 0.0
    assert not any("char" in name.lower() for name in BudgetEnvelope.model_fields)


# ── option-B fold-in (plan phase) ────────────────────────────────────────────


def _noted_file(tmp_path: Path, *, two_sections: bool = False) -> Path:
    """A directed file whose section text is DELIBERATELY different from the last take's,
    so a fold-in based on the file vs. the last take is distinguishable."""
    sections = [
        DirectedSection(section_id="intro", heading="Intro", text="FILE INTRO TEXT.",
                        voice_id="voice-1", model="eleven_v3", settings={}),
    ]
    if two_sections:
        sections.append(
            DirectedSection(section_id="body", heading="Body", text="FILE BODY TEXT.",
                            voice_id="voice-1", model="eleven_v3", settings={})
        )
    path = tmp_path / "noted.directed.md"
    write_directed_script(DirectedScript(project_id="ep-12", domain="tech", sections=sections), path)
    return path


def _noted_take(section_id="intro") -> Take:
    take = Take(text="LAST TAKE TEXT.", voice_id="voice-1", model="eleven_v3",
                section_id=section_id, project_id="ep-12", notes="slow it down",
                chain_root_id="root-x")
    take.chain_root_id = "root-x"
    return take


def _revised() -> DirectedSection:
    return DirectedSection(section_id="intro", heading="Intro", text="REVISED TEXT.",
                           voice_id="voice-1", model="eleven_v3", settings={"stability": "robust"})


def _llm_client(response_text: str, input_tokens: int = 300, output_tokens: int = 150) -> MagicMock:
    msg = MagicMock()
    msg.content = [MagicMock(text=response_text)]
    msg.usage = MagicMock(input_tokens=input_tokens, output_tokens=output_tokens)
    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(return_value=msg)
    return client


@pytest.mark.asyncio
async def test_fold_in_fires_when_last_take_has_note(tmp_path: Path) -> None:
    directed = _noted_file(tmp_path)
    prev = _noted_take()
    store = _mock_store(latest=prev)
    tts = _mock_tts()
    with patch("voiceover_direction.generation.retrieve_context", AsyncMock(return_value=RetrievedContext())), \
         patch("voiceover_direction.generation.redirect_section", AsyncMock(return_value=_revised())) as redir:
        await _run(directed, section_id="intro", store=store, tts_client=tts,
                  llm_client=MagicMock(), memory_store=MagicMock())

    redir.assert_awaited_once()
    take: Take = store.upsert_take.call_args.args[0]
    assert take.text == "REVISED TEXT."            # the take records the revised direction
    assert take.settings == {"stability": "robust"}
    assert take.parent_take_id == prev.entry_id    # parents off the noted take
    assert take.chain_root_id == "root-x"          # keeps the noted take's chain root
    # TTS spoke the revised text, not the file text.
    assert tts.synthesize.call_args.args[0] == "REVISED TEXT."


@pytest.mark.asyncio
async def test_base_is_last_take_not_file(tmp_path: Path) -> None:
    # Load-bearing: re-direction starts from the LAST TAKE's text + note, not the file markup.
    directed = _noted_file(tmp_path)
    prev = _noted_take()
    store = _mock_store(latest=prev)
    with patch("voiceover_direction.generation.retrieve_context", AsyncMock(return_value=RetrievedContext())), \
         patch("voiceover_direction.generation.redirect_section", AsyncMock(return_value=_revised())) as redir:
        await _run(directed, section_id="intro", store=store, tts_client=_mock_tts(),
                  llm_client=MagicMock(), memory_store=MagicMock())

    base_take = redir.call_args.args[0]
    note_arg = redir.call_args.args[2]
    assert base_take.text == "LAST TAKE TEXT."   # the last take, NOT "FILE INTRO TEXT."
    assert note_arg == "slow it down"


@pytest.mark.asyncio
async def test_raw_skips_redirection(tmp_path: Path) -> None:
    directed = _noted_file(tmp_path)
    store = _mock_store(latest=_noted_take())  # has a note, but --raw must ignore it
    tts = _mock_tts()
    with patch("voiceover_direction.generation.redirect_section", AsyncMock()) as redir:
        await _run(directed, section_id="intro", raw=True, store=store, tts_client=tts,
                  llm_client=MagicMock(), memory_store=MagicMock())

    redir.assert_not_called()
    take: Take = store.upsert_take.call_args.args[0]
    assert take.text == "FILE INTRO TEXT."   # verbatim file markup
    assert tts.synthesize.call_args.args[0] == "FILE INTRO TEXT."


@pytest.mark.asyncio
async def test_no_note_skips_redirection(tmp_path: Path) -> None:
    # Regression: last take without a note → Step-3 behavior (file markup spoken as-is).
    directed = _noted_file(tmp_path)
    prev = Take(text="LAST TAKE TEXT.", voice_id="voice-1", model="eleven_v3",
                section_id="intro", project_id="ep-12")  # notes=None
    store = _mock_store(latest=prev)
    with patch("voiceover_direction.generation.redirect_section", AsyncMock()) as redir:
        await _run(directed, section_id="intro", store=store, tts_client=_mock_tts(),
                  llm_client=MagicMock(), memory_store=MagicMock())

    redir.assert_not_called()
    take: Take = store.upsert_take.call_args.args[0]
    assert take.text == "FILE INTRO TEXT."


@pytest.mark.asyncio
async def test_redirection_cost_lands_in_budget_characters_do_not(tmp_path: Path) -> None:
    import json

    from voiceover_direction.generation import plan_generation, spend_generation

    directed = _noted_file(tmp_path)
    store = _mock_store(latest=_noted_take())
    redirect_json = json.dumps({"sections": [{
        "section_id": "intro", "directed_text": "REVISED TEXT.", "voice_id": "voice-1",
        "voice_characteristics": None, "model": "eleven_v3", "settings": {}, "reasoning": "x",
    }], "overall_reasoning": "y"})
    llm = _llm_client(redirect_json)

    with patch("voiceover_direction.generation.retrieve_context", AsyncMock(return_value=RetrievedContext())):
        plan = await plan_generation(directed, section_id="intro", store=store,
                                     llm_client=llm, memory_store=MagicMock())

    # The Claude re-direction cost is recorded in the budget.
    assert plan.cost_usd > 0
    assert plan.plans[0].was_redirected is True

    # The spend run makes no Claude call → its budget cost is zero (characters are orthogonal).
    p1, p2 = _patches()
    with p1, p2:
        result = await spend_generation(plan, store=store, tts_client=_mock_tts())
    assert result.cost_usd == 0.0


@pytest.mark.asyncio
async def test_cost_cap_truncates_to_partial(tmp_path: Path) -> None:
    import json

    from voiceover_direction.generation import plan_generation

    directed = _noted_file(tmp_path, two_sections=True)
    store = _mock_store(latest=_noted_take())  # both sections get a noted prev → both re-direct
    redirect_json = json.dumps({"sections": [{
        "section_id": "intro", "directed_text": "REVISED.", "voice_id": "voice-1",
        "voice_characteristics": None, "model": "eleven_v3", "settings": {}, "reasoning": "x",
    }], "overall_reasoning": "y"})
    llm = _llm_client(redirect_json)  # ~$0.003 per call, exceeds the tiny cap below

    tiny = BudgetEnvelope(max_items=None, max_depth=0, max_cost_usd=0.000001, max_wall_time_sec=600)
    with patch("voiceover_direction.generation.retrieve_context", AsyncMock(return_value=RetrievedContext())):
        plan = await plan_generation(directed, all_sections=True, budget=tiny, store=store,
                                     llm_client=llm, memory_store=MagicMock())

    assert plan.status == "partial"          # cost cap hit after the first re-direction
    assert len(plan.plans) < 2               # the second section was not planned
