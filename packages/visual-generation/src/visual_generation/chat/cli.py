"""`visual-generation chat`: wires ChatConfig, a provider-neutral engine and the REPL."""

from __future__ import annotations

import asyncio
import sys

import click
from agent_runtime.config import get_config
from agent_shell.config import ShellSettings
from agent_shell.engine.factory import EngineConfigError, make_engine
from agent_shell.repl.app import ShellApp
from agent_shell.session.api import Session
from rich.text import Text

from visual_generation.chat.config import build_chat_config
from visual_generation.chat.state import ChatState


def run_chat(
    provider: str, model: str | None, project: str | None, resume_id: str | None, dry_run: bool,
    gpu_budget: float = 5.0,
) -> None:
    if not sys.stdin.isatty():
        raise click.ClickException("chat needs an interactive terminal (stdin is not a TTY).")
    config = get_config()
    try:
        state = ChatState(project=project, config=config)
    except ValueError as e:
        raise click.BadParameter(str(e), param_hint="--project") from e
    try:
        engine = make_engine(provider, model)
    except EngineConfigError as e:
        raise click.ClickException(str(e)) from e
    settings = ShellSettings(agent_data_dir=config.agent_data_dir, dry_run=dry_run, gpu_budget_usd=gpu_budget)
    session = Session(build_chat_config(state), settings, engine)
    state.session = session          # session id and current engine, for evaluation records
    app = ShellApp(session, engine_factory=make_engine)
    # a long render or install says what it is waiting for, since its result only arrives at the end
    state.notify = lambda text: app.console.print(Text(f"  {text}", style="dim"))
    asyncio.run(app.run(resume_id))
