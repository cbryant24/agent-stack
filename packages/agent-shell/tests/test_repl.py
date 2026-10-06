from __future__ import annotations

import io
import json
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from prompt_toolkit import PromptSession
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from rich.console import Console

from agent_shell.config import ShellSettings
from agent_shell.demo import demo_config, demo_engine
from agent_shell.engine.fake import FakeEngine
from agent_shell.repl.app import ShellApp, _bindings
from agent_shell.repl.commands import ReplContext, handle_slash
from agent_shell.session.api import Session
from agent_shell.session.store import SessionStore

pytestmark = pytest.mark.asyncio


@contextmanager
def app_with_input(settings: ShellSettings, typed: str, engine: FakeEngine | None = None,
                   **kw: bool) -> Iterator[tuple[ShellApp, io.StringIO]]:
    out = io.StringIO()
    console = Console(file=out, force_terminal=False, width=100)
    with create_pipe_input() as pipe:
        pipe.send_text(typed)
        prompt: PromptSession[str] = PromptSession(
            input=pipe, output=DummyOutput(), key_bindings=_bindings(), multiline=True
        )
        s = ShellSettings(**{**settings.model_dump(), **kw})
        session = Session(demo_config(), s, engine or demo_engine())
        yield ShellApp(session, console=console, prompt=prompt), out


async def test_slash_commands_make_no_llm_call(settings: ShellSettings) -> None:
    engine = demo_engine()
    session = Session(demo_config(), settings, engine)
    await session.start()
    ctx = ReplContext(session, {"fake": engine})

    assert "/dry-run" in (await handle_slash("/help", ctx)).output
    assert (await handle_slash("/exit", ctx)).exit
    assert "dry-run is off" in (await handle_slash("/dry-run", ctx)).output
    assert "dry-run is on" in (await handle_slash("/dry-run on", ctx)).output and session.dry_run
    assert "usage" in (await handle_slash("/dry-run maybe", ctx)).output
    tools = (await handle_slash("/tools", ctx)).output
    assert "gpu_spend" in tools and "memory_write" in tools and "read" in tools
    assert "repl: $0.9" not in (await handle_slash("/cost", ctx)).output
    assert "$1.0000" in (await handle_slash("/budget", ctx)).output
    assert "no tool calls yet" == (await handle_slash("/audit", ctx)).output
    assert "fake-1" in (await handle_slash("/model", ctx)).output
    assert "model: m2" == (await handle_slash("/model m2", ctx)).output and engine.model == "m2"
    assert "fake" in (await handle_slash("/provider", ctx)).output
    assert "unknown provider" in (await handle_slash("/provider zzz", ctx)).output
    assert "unknown command" in (await handle_slash("/nope", ctx)).output
    assert engine.turn == 0  # nothing reached the engine


async def test_session_slash_commands(settings: ShellSettings) -> None:
    session = Session(demo_config(), settings, demo_engine())
    await session.start()
    ctx = ReplContext(session)
    await handle_slash("/session rename my title", ctx)
    assert "my title" in (await handle_slash("/session list", ctx)).output
    assert session.session_id in (await handle_slash("/session list", ctx)).output
    res = await handle_slash(f"/session resume {session.session_id}", ctx)
    assert res.resume_id == session.session_id
    assert "unknown session" in (await handle_slash("/session resume nope", ctx)).output


async def test_provider_switch_keeps_the_session(settings: ShellSettings) -> None:
    session = Session(demo_config(), settings, demo_engine())
    await session.start()
    sid = session.session_id
    other = FakeEngine(model="other-9")
    ctx = ReplContext(session, {"fake2": other})
    assert "other-9" in (await handle_slash("/provider fake2", ctx)).output
    assert session.engine is other and session.session_id == sid and other.started_with is not None


async def test_repl_demo_turns_confirm_panel_and_proposals(settings: ShellSettings) -> None:
    # turn 1 (read tool), turn 2 (memory write: edit it), turn 3 (GPU: accept), /exit,
    # then the end-of-session proposal: defer.
    typed = (
        "look something up\r"
        "save a lesson\r" "e\r" + json.dumps({"statement": "edited lesson"}) + "\r"
        "render it\r" "y\r"
        "/exit\r" "d\r"
    )
    with app_with_input(settings, typed) as (app, out):
        report = await app.run()
    text = out.getvalue()
    assert "found 3 notes" in text
    assert "save_lesson" in text and "memory_write" in text      # confirm panel title
    assert "saved lesson: edited lesson" in text
    assert "render" in text and "gpu_spend" in text and "rendered 'a lit room'" in text
    assert "turn $" in text and "session $" in text               # cost footer
    assert len(report.deferred) == 1 and report.accepted == []
    assert len(list((settings.agent_data_dir / "drafts" / "demo").glob("*.json"))) == 1


async def test_repl_rejecting_the_gpu_confirm_runs_nothing(settings: ShellSettings) -> None:
    typed = "a\rb\rrender\rn\r/exit\rn\r"
    with app_with_input(settings, typed) as (app, out):
        await app.run()
    assert "Declined by the user" in out.getvalue()
    assert "rendered 'a lit room'" not in out.getvalue()


async def test_repl_bad_confirm_answer_reprompts(settings: ShellSettings) -> None:
    typed = "a\rb\rrender\rzzz\rn\r/exit\rn\r"
    with app_with_input(settings, typed) as (app, out):
        await app.run()
    assert "enter one of" in out.getvalue()


async def test_repl_dry_run_flag_and_slash_toggle(settings: ShellSettings) -> None:
    typed = "a\rb\rrender\r/exit\rn\r"
    with app_with_input(settings, typed, dry_run=True) as (app, out):
        await app.run()
    t = out.getvalue()
    assert "dry-run is on" in t and "[dry-run] would run render" in t
    assert "rendered 'a lit room'" not in t


async def test_repl_resume_replays_the_earlier_session(settings: ShellSettings) -> None:
    with app_with_input(settings, "hello\r/exit\rn\r") as (app, _):
        await app.run()
        sid = app.session.session_id
    with app_with_input(settings, "more\r/exit\rn\r", FakeEngine()) as (app2, out2):
        await app2.run(resume_id=sid)
    assert f"session {sid}" in out2.getvalue()
    users = [m["content"] for m in app2.session.transcript() if m["role"] == "user"]
    assert users == ["hello", "more"]
    store = SessionStore(settings.db_path)
    assert store.exists(sid)


async def test_multiline_input_via_escape_enter(settings: ShellSettings) -> None:
    with app_with_input(settings, "line one\x1b\rline two\r/exit\rn\r", FakeEngine()) as (app, _):
        await app.run()
    users = [m["content"] for m in app.session.transcript() if m["role"] == "user"]
    assert users == ["line one\nline two"]


async def test_real_prompt_completes_slash_commands(settings: ShellSettings) -> None:
    """Builds the production PromptSession (not the injected test one)."""
    from prompt_toolkit.completion import CompleteEvent
    from prompt_toolkit.document import Document

    app = ShellApp(Session(demo_config(), settings, demo_engine()), console=Console(file=io.StringIO()))
    assert app.prompt.completer is not None
    got = [c.text for c in app.prompt.completer.get_completions(Document("/dr"), CompleteEvent())]
    assert got == ["/dry-run"]
    assert (settings.agent_data_dir / "shell-history").is_dir()
