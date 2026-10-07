"""Agent extension points: life-cycle hooks, agent slash commands, tools run outside a turn,
the idle timer, and a confirm panel that shows a complete preview alone."""

from __future__ import annotations

import asyncio
import io
from typing import Any

import pytest
from rich.console import Console

from agent_shell.config import ShellHooks, ShellSettings
from agent_shell.demo import demo_config, demo_engine
from agent_shell.guard.gate import AutoConfirmer, ConfirmRequest, Decision
from agent_shell.repl.app import _IDLE, PromptConfirmer, ShellApp
from agent_shell.repl.commands import ReplContext, handle_slash
from agent_shell.session.api import Session
from agent_shell.testing import Counter, make_tool
from agent_shell.tools.registry import EffectClass
from agent_shell.ui import ScriptedUI

from .test_repl import app_with_input

pytestmark = pytest.mark.asyncio


async def test_hooks_run_at_start_after_each_turn_and_before_exit(settings: ShellSettings) -> None:
    seen: list[str] = []

    def hook(name: str) -> Any:
        async def run(ui: Any) -> None:
            seen.append(name)
            ui.say(f"<{name}>")
        return run

    with app_with_input(settings, "hello\r/cost\r/exit\r") as (app, out):
        app.session.config = app.session.config.model_copy(update={"on_session_end": None, "hooks": ShellHooks(
            on_start=hook("start"), on_turn_end=hook("turn"), on_exit=hook("exit"))})
        await app.run()
    assert seen == ["start", "turn", "exit"]                    # a slash command is not a turn
    text = out.getvalue()
    assert text.index("<start>") < text.index("<turn>") < text.index("<exit>")


async def test_a_failing_hook_is_reported_and_the_repl_carries_on(settings: ShellSettings) -> None:
    async def boom(ui: Any) -> None:
        raise RuntimeError("status unavailable")

    with app_with_input(settings, "/cost\r/exit\r") as (app, out):
        app.session.config = app.session.config.model_copy(update={"on_session_end": None, "hooks": ShellHooks(on_start=boom)})
        await app.run()
    assert "hook failed: RuntimeError: status unavailable" in out.getvalue() and "spent" in out.getvalue()


async def test_an_agent_slash_command_is_dispatched_listed_and_makes_no_llm_call(settings: ShellSettings) -> None:
    async def pod(args: list[str], ui: Any) -> str:
        ui.say("working")
        return "pod " + " ".join(args)

    async def broken(args: list[str], ui: Any) -> str:
        raise ValueError("nope")

    engine = demo_engine()
    config = demo_config().model_copy(update={
        "slash_commands": {"/pod": pod, "/broken": broken}, "slash_help": "/pod rebuild   the runbook"})
    session = Session(config, settings, engine)
    await session.start()
    ui = ScriptedUI(session)
    ctx = ReplContext(session, ui=ui)
    assert (await handle_slash("/pod rebuild status", ctx)).output == "pod rebuild status" and ui.said == ["working"]
    assert "/pod rebuild   the runbook" in (await handle_slash("/help", ctx)).output
    assert (await handle_slash("/broken", ctx)).output == "ValueError: nope"
    assert "needs an interactive front end" in (await handle_slash("/pod x", ReplContext(session))).output
    assert "unknown command" in (await handle_slash("/nope", ctx)).output and engine.turn == 0


async def test_a_tool_run_outside_a_turn_goes_through_the_gate_dry_run_and_audit(
    settings: ShellSettings, counter: Counter
) -> None:
    config = demo_config().model_copy(update={"tool_pack": lambda: [
        make_tool("render", EffectClass.GPU_SPEND, counter, cost=0.2),
        make_tool("wipe", EffectClass.DESTRUCTIVE_LOCAL, counter),
    ]})
    session = Session(config, settings, demo_engine())
    await session.start()

    ui = ScriptedUI(session, decisions=["reject", "accept"])
    assert (await ui.run_tool("render", {"text": "a"})).data.get("rejected") and counter.calls == []
    assert (await ui.run_tool("render", {"text": "b"})).text == "render ran b" and session.budgets.gpu.spent == 0.2
    assert [r.tool for r in ui.requests] == ["render", "render"]             # the front end was asked, not the turn queue

    assert (await ui.run_tool("wipe", {"text": "c"}, confirmed=True)).text == "wipe ran c" and len(ui.requests) == 2
    session.dry_run = True
    assert (await ui.run_tool("wipe", {"text": "d"}, confirmed=True)).data == {"dry_run": True}
    assert counter.calls == ["b", "c"] and (await ui.run_tool("nope")).is_error
    assert session.audit is not None
    assert [r["decision"] for r in session.audit.read()] == ["reject", "allow", "proposal_accept", "dry_run"]


async def test_a_complete_preview_is_shown_without_the_raw_arguments(counter: Counter, settings: ShellSettings) -> None:
    spec = make_tool("render", EffectClass.GPU_SPEND, counter).model_copy(update={"preview_is_complete": True})
    c = AutoConfirmer("accept")
    session = Session(demo_config().model_copy(update={"tool_pack": lambda: [spec]}), settings, demo_engine(), confirmer=c)
    await session.start()
    await session.run_tool("render", {"text": "zzz"})
    assert c.requests[0].show_args is False and c.requests[0].preview == "preview zzz"

    class OneKey:
        async def prompt_async(self, *a: Any, **k: Any) -> str:
            return "y"

    for show, expect_json in ((False, False), (True, True)):
        out = io.StringIO()
        prompter = PromptConfirmer(Console(file=out, force_terminal=False, width=80), OneKey())  # type: ignore[arg-type]
        await prompter.ask(ConfirmRequest(tool="render", effect=EffectClass.GPU_SPEND, args={"text": "zzz"},
                                          preview="Create a pod.", show_args=show))
        assert "Create a pod." in out.getvalue() and ('"text": "zzz"' in out.getvalue()) is expect_json


class SlowPrompt:
    """A prompt nobody answers until `lines` are fed; records cancellations."""

    def __init__(self, lines: list[str]) -> None:
        self.lines, self.cancelled, self.waits = lines, 0, 0

    async def prompt_async(self, *a: Any, **k: Any) -> str:
        self.waits += 1
        if self.waits == 1:                                    # the first prompt sits idle
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                self.cancelled += 1
                raise
        if not self.lines:
            raise EOFError
        return self.lines.pop(0)


async def test_the_idle_timer_ends_a_waiting_prompt_and_runs_the_idle_hook(settings: ShellSettings) -> None:
    fired: list[str] = []
    due: list[float | None] = [0.05]

    async def on_idle(ui: Any) -> None:
        fired.append("idle")
        due[0] = None                                          # handled: no further check-in due

    config = demo_config().model_copy(update={
        "on_session_end": None, "hooks": ShellHooks(idle_due_in=lambda: due[0], on_idle=on_idle)})
    session = Session(config, settings, demo_engine())
    prompt = SlowPrompt(["/exit"])
    app = ShellApp(session, console=Console(file=io.StringIO()), prompt=prompt)  # type: ignore[arg-type]
    await asyncio.wait_for(app.run(), 5)
    assert fired == ["idle"] and prompt.cancelled == 1 and prompt.waits == 2

    session2 = Session(demo_config(), settings, demo_engine())  # no hooks: the prompt is read directly
    app2 = ShellApp(session2, console=Console(file=io.StringIO()), prompt=SlowPrompt([]))  # type: ignore[arg-type]
    task = asyncio.ensure_future(app2._read_line())
    await asyncio.sleep(0.1)
    assert not task.done()
    task.cancel()
    assert _IDLE


async def test_scripted_ui_answers_choices_and_reports_an_unexpected_question() -> None:
    ui = ScriptedUI(None, choices=["y", None], decisions=[Decision(kind="accept")])
    assert await ui.choose("delete?", {"y": "yes", "n": "no"}) == "y"
    assert await ui.choose("still there?", {"k": "keep"}, timeout=1) is None
    with pytest.raises(AssertionError, match="unexpected question"):
        await ui.choose("again?", {"y": "yes"})
