from __future__ import annotations

import pytest

from agent_shell.tools.registry import EffectClass, Registry
from agent_shell.testing import Counter, make_tool


def test_duplicate_names_are_rejected(counter: Counter) -> None:
    r = Registry([make_tool("a", EffectClass.READ, counter)])
    with pytest.raises(ValueError, match="duplicate"):
        r.register(make_tool("a", EffectClass.NONE, counter))


def test_schema_comes_from_the_input_model(counter: Counter) -> None:
    r = Registry([make_tool("a", EffectClass.READ, counter)])
    assert "text" in r.schema("a")["properties"]
    assert r.names() == ["a"]
    with pytest.raises(KeyError):
        r.get("nope")
