from __future__ import annotations

import asyncio
import os
from pathlib import Path

import click

from agent_shell.config import ShellSettings
from agent_shell.demo import demo_config, demo_engine
from agent_shell.repl.app import ShellApp
from agent_shell.session.api import Session


def _data_dir() -> Path:
    return Path(os.environ.get("AGENT_DATA_DIR", "~/agent-data")).expanduser()


@click.group()
def cli() -> None:
    """Provider-neutral chat shell."""


@cli.command()
@click.option("--dry-run", is_flag=True, help="Gated tools describe what they would do and run nothing.")
@click.option("--resume", "resume_id", default=None, help="Resume a session id.")
@click.option("--data-dir", type=click.Path(path_type=Path), default=None,
              help="Where sessions and logs go (default: AGENT_DATA_DIR or ~/agent-data).")
def demo(dry_run: bool, resume_id: str | None, data_dir: Path | None) -> None:
    """Chat with a scripted fake engine: streaming, confirms, dry-run, resume. No keys, no spend."""
    settings = ShellSettings(
        agent_data_dir=(data_dir or _data_dir()).expanduser(), dry_run=dry_run, gpu_budget_usd=0.25
    )
    session = Session(demo_config(), settings, demo_engine())
    asyncio.run(ShellApp(session).run(resume_id))


if __name__ == "__main__":
    cli()
