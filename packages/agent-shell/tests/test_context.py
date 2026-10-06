from __future__ import annotations

from typing import Any

from agent_shell.context import TRUNCATED, balance_tool_calls, trim_history


def turn(n: int, *, tool: bool = False, result: str = "ok") -> list[dict[str, Any]]:
    msgs: list[dict[str, Any]] = [{"role": "user", "content": f"u{n}"}]
    if tool:
        msgs += [
            {"role": "assistant", "content": "", "tool_calls": [{"id": f"c{n}", "name": "t", "args": {}}]},
            {"role": "tool", "content": result, "tool_call_id": f"c{n}", "name": "t", "is_error": False},
        ]
    msgs.append({"role": "assistant", "content": f"a{n}"})
    return msgs


def test_keeps_the_last_n_turns_starting_on_a_user_message() -> None:
    hist = [m for n in range(5) for m in turn(n, tool=True)]
    out = trim_history(hist, last_n_turns=2)
    assert out[0] == {"role": "user", "content": "u3"}
    assert [m["content"] for m in out if m["role"] == "user"] == ["u3", "u4"]


def test_window_never_separates_a_call_from_its_result() -> None:
    out = trim_history([m for n in range(6) for m in turn(n, tool=True)], last_n_turns=3)
    calls = {c["id"] for m in out for c in m.get("tool_calls", [])}
    results = {m["tool_call_id"] for m in out if m["role"] == "tool"}
    assert calls == results and len(calls) == 3


def test_short_history_is_untouched() -> None:
    hist = turn(0) + turn(1, tool=True)
    assert trim_history(hist, last_n_turns=20) == hist


def test_tool_text_is_capped_with_a_marker() -> None:
    out = trim_history(turn(0, tool=True, result="x" * 5000), tool_text_cap=100)
    tool = next(m for m in out if m["role"] == "tool")
    assert len(tool["content"]) == 100 and tool["content"].endswith(TRUNCATED)


def test_does_not_mutate_its_input() -> None:
    hist = turn(0, tool=True, result="x" * 5000)
    trim_history(hist, tool_text_cap=100)
    assert len(hist[2]["content"]) == 5000


def test_balance_adds_a_result_for_an_unanswered_call_and_drops_orphans() -> None:
    msgs: list[dict[str, Any]] = [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "x", "name": "t", "args": {}}]},
        {"role": "tool", "content": "stray", "tool_call_id": "nope", "name": "t"},
    ]
    out = balance_tool_calls(msgs)
    assert [m["role"] for m in out] == ["user", "assistant", "tool"]
    assert out[2]["tool_call_id"] == "x" and out[2]["is_error"] is True
