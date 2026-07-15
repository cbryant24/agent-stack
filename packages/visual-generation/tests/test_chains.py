"""Tests for the craft chain's prompt assembly (visual_generation.chains).

Focus: canon characters the scene names are surfaced INTO the craft prompt by name, so
the LLM composes them in rather than dropping them. The cast block carries names and
asset ids only — never appearance prose (identity is model/asset-level, audit §5).
"""

from __future__ import annotations

from visual_generation.canon import CanonSubject
from visual_generation.chains import _build_user_message, _cast_block
from visual_generation.retrieval import RetrievedContext


def test_cast_block_lists_each_subject_with_plain_aliases_and_asset_id() -> None:
    subj = CanonSubject(
        aliases=["the narrator", "narrator", "@tok", "Chris"],
        id="narrator_v1",
    )
    block = _cast_block([subj])
    assert '"the narrator"' in block          # primary alias names the character
    assert "narrator" in block and "Chris" in block  # other plain aliases listed
    assert "@tok" not in block                # token aliases aren't listed as "also called"
    assert "narrator_v1" in block             # the asset-reference id
    assert "locked" not in block.lower()      # no appearance prose channel remains


def test_cast_block_omits_asset_suffix_when_no_id() -> None:
    subj = CanonSubject(aliases=["Celeste"])
    block = _cast_block([subj])
    assert '"Celeste"' in block
    assert "[asset:" not in block


def test_cast_block_empty_without_cast() -> None:
    assert _cast_block(None) == ""
    assert _cast_block([]) == ""


def test_text2img_user_message_includes_the_cast() -> None:
    subj = CanonSubject(aliases=["Chris"], id="narrator_v1")
    msg = _build_user_message("a wide rooftop shot", RetrievedContext(), None, [], cast=[subj])
    assert "Project canon" in msg
    assert "Chris" in msg
    assert "narrator_v1" in msg


def test_text2img_user_message_omits_cast_section_when_none() -> None:
    msg = _build_user_message("a wide rooftop shot", RetrievedContext(), None, [], cast=None)
    assert "Project canon" not in msg
