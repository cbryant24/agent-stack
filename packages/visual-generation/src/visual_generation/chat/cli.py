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

from visual_generation.chat.config import build_chat_config
from visual_generation.chat.state import ChatState


def run_chat(
    provider: str, model: str | None, project: str | None, resume_id: str | None, dry_run: bool
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
    settings = ShellSettings(agent_data_dir=config.agent_data_dir, dry_run=dry_run)
    session = Session(build_chat_config(state), settings, engine)
    asyncio.run(ShellApp(session, engine_factory=make_engine).run(resume_id))
