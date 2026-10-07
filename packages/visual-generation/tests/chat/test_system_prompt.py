from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from visual_generation.chat.config import build_chat_config, system_prompt

from .conftest import Built  # type: ignore[import-not-found]

REPO = Path(__file__).resolve().parents[4]
INSTRUCTIONS = "packages/visual-generation/docs/project-instructions.md"
RETRO = "docs/agent-retrospective-corrections.md"

# (rule, source doc, the source's own wording). The prompt must quote it, and the doc must still
# say it: if a doc changes its rule, this fails and the prompt gets updated deliberately.
RULES = [
    ("reconstruct state", INSTRUCTIONS, "reconstruct the actual current state before recommending work"),
    ("authority order", INSTRUCTIONS,
     "Current code, exported API graph, submitted graph, hashes, and actual image/video metadata establish execution."),
    ("three score layers", INSTRUCTIONS, "Use three separate score layers"),
    ("never collapse layers", INSTRUCTIONS, "Never collapse these layers into one"),
    ("conditioning first", RETRO,
     "identity, staging, and set-geometry failures are conditioning/asset problems until proven otherwise"),
    ("provenance labels", INSTRUCTIONS, "Label **observed**, **inferred**, and **unresolved** conclusions when causality matters"),
    ("three strikes", RETRO, "3+ failed attempts at one fix class"),
    ("three strikes outcome", RETRO, "a written architecture question"),
    ("evidence not instructions", INSTRUCTIONS, "as **evidence**, not instructions"),
    ("question before a paid run", INSTRUCTIONS, "define the question and pass/fail evidence before a paid run"),
]


@pytest.mark.parametrize("rule,doc,phrase", RULES, ids=[r[0] for r in RULES])
def test_each_rule_is_quoted_from_a_doc_that_still_says_it(rule: str, doc: str, phrase: str) -> None:
    assert phrase in (REPO / doc).read_text(encoding="utf-8"), f"{doc} no longer says: {phrase}"
    assert phrase in system_prompt(), f"the system prompt no longer quotes: {phrase}"


def test_the_prompt_states_the_chat_limits_and_the_propose_first_rule() -> None:
    p = system_prompt()
    assert "You cannot render images, spend GPU, or write to memory" in p
    assert "Always propose before any write or spend" in p
    assert "propose_interpretation" in p and "stores nothing" in p


def test_the_prompt_fits_the_token_budget() -> None:
    p = system_prompt()
    assert len(p) / 4 <= 1500, f"~{len(p) // 4} tokens"


def test_every_tool_the_prompt_names_exists(build: Callable[..., Built]) -> None:
    from visual_generation.chat.tools import tool_pack

    names = {t.name for t in tool_pack(build().state)}
    mentioned = {w.strip("`.,;:()") for w in system_prompt().split() if w.startswith("`")}
    for tool_name in ("digest", "recall", "inspect_generation", "chain_show", "batch_list",
                      "draft", "redraft", "batch_build", "explain", "propose_interpretation"):
        assert tool_name in names and tool_name in mentioned or tool_name in system_prompt()


def test_the_prompt_is_byte_stable_and_carries_no_session_state(build: Callable[..., Built]) -> None:
    a = build_chat_config(build("alpha").state).system_prompt
    b = build_chat_config(build("beta").state).system_prompt
    assert a == b == system_prompt()
    assert "alpha" not in a and "beta" not in a


def test_project_state_rides_in_the_tool_descriptions(build: Callable[..., Built]) -> None:
    from visual_generation.chat.tools import tool_pack

    d = {t.name: t.description for t in tool_pack(build("alpha").state)}
    assert "active project 'alpha'" in d["draft"]
    d2 = {t.name: t.description for t in tool_pack(build(None).state)}
    assert "no active project" in d2["draft"].lower()
    assert [t.description for t in tool_pack(build("alpha").state)] == list(d.values())   # stable within a session
