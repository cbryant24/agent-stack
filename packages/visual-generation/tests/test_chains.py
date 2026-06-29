"""Tests for the craft chain's prompt assembly (visual_generation.chains).

Focus: canon characters the scene names are surfaced INTO the craft prompt, so the LLM
composes them in rather than dropping them (the upstream half of canon enforcement).
"""

from __future__ import annotations

from visual_generation.canon import CanonSubject
from visual_generation.chains import _build_user_message, _cast_block
from visual_generation.retrieval import RetrievedContext


def test_cast_block_lists_each_subject_with_plain_aliases_and_locked() -> None:
    subj = CanonSubject(
        aliases=["the narrator", "narrator", "@tok", "Chris"],
        locked="a felt puppet with dreadlocks to mid-back",
    )
    block = _cast_block([subj])
    assert '"the narrator"' in block          # primary alias names the character
    assert "narrator" in block and "Chris" in block  # other plain aliases listed
    assert "@tok" not in block                # token aliases aren't listed as "also called"
    assert "dreadlocks to mid-back" in block  # the locked appearance


def test_cast_block_empty_without_cast() -> None:
    assert _cast_block(None) == ""
    assert _cast_block([]) == ""


def test_text2img_user_message_includes_the_cast() -> None:
    subj = CanonSubject(aliases=["Chris"], locked="a felt puppet with dreadlocks")
    msg = _build_user_message("a wide rooftop shot", RetrievedContext(), None, [], cast=[subj])
    assert "Project canon" in msg
    assert "Chris" in msg
    assert "dreadlocks" in msg


def test_text2img_user_message_omits_cast_section_when_none() -> None:
    msg = _build_user_message("a wide rooftop shot", RetrievedContext(), None, [], cast=None)
    assert "Project canon" not in msg
