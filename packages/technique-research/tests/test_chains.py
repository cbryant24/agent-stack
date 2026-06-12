from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from technique_research import chains
from technique_research.models import GroundedReference, IdentificationInput


def _msg(text: str):
    return SimpleNamespace(
        content=[SimpleNamespace(text=text)],
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )


def _client(text: str):
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=_msg(text))
    return client


@pytest.mark.asyncio
async def test_identify_parses_domains_and_infers_scope() -> None:
    payload = {
        "scope": "generation",
        "grounded_reference_summary": "X is a Flux-styled look.",
        "domains": [
            {"name": "Flux prompting", "why_it_matters": "core", "priority": 2,
             "scope": "generation", "search_query": "flux style prompting"},
            {"name": "LoRA selection", "why_it_matters": "identity", "priority": 1,
             "scope": "generation", "search_query": "lora selection"},
        ],
    }
    inp = IdentificationInput(goal="images like X")
    domains, summary, scope = await identify_call(payload, inp)
    assert scope == "generation"
    assert summary.startswith("X is a Flux")
    # Sorted by priority ascending.
    assert [d.name for d in domains] == ["LoRA selection", "Flux prompting"]


@pytest.mark.asyncio
async def test_explicit_scope_overrides_model() -> None:
    payload = {"scope": "generation", "grounded_reference_summary": "",
               "domains": [{"name": "Cuts", "search_query": "cuts"}]}
    inp = IdentificationInput(goal="a video like X", scope="editing")
    _domains, _summary, scope = await identify_call(payload, inp)
    assert scope == "editing"  # the explicit flag wins, preventing misroute


async def identify_call(payload, inp):
    client = _client(json.dumps(payload))
    return await chains.identify_techniques(inp, GroundedReference(), "TOOLSET", "", client)


@pytest.mark.asyncio
async def test_assess_reference_flags_grounding() -> None:
    client = _client(json.dumps(
        {"needs_grounding": True, "tavily_query": "Xenoz edits style", "preliminary_summary": "a creator"}
    ))
    inp = IdentificationInput(goal="like Xenoz edits")
    out = await chains.assess_reference(inp, None, client)
    assert out["needs_grounding"] is True
    assert out["tavily_query"] == "Xenoz edits style"


@pytest.mark.asyncio
async def test_assess_reference_degrades_on_bad_json() -> None:
    client = _client("not json at all")
    out = await chains.assess_reference(IdentificationInput(goal="g"), None, client)
    assert out["needs_grounding"] is False


@pytest.mark.asyncio
async def test_curate_findings_parses_techniques_strips_fences() -> None:
    body = json.dumps({"techniques": [
        {"technique": "Speed ramp", "description": "d", "why_it_matters": "w",
         "application_notes": "a", "toolset_fit": "Resolve", "upgrade_flag": None},
    ]})
    client = _client(f"```json\n{body}\n```")
    out = await chains.curate_findings(
        "goal", "editing", [], {}, "TOOLSET", client
    )
    assert out[0]["technique"] == "Speed ramp"


def test_image_block_unsupported_type_returns_none(tmp_path) -> None:
    p = tmp_path / "ref.bmp"
    p.write_bytes(b"\x00\x01")
    assert chains._image_block(p) is None


def test_image_block_encodes_png(tmp_path) -> None:
    p = tmp_path / "ref.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n")
    block = chains._image_block(p)
    assert block is not None
    assert block["type"] == "image"
    assert block["source"]["media_type"] == "image/png"
