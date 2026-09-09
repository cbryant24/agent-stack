"""Click CLI entry point for the video-clipping agent.

The binary is `clip` (see [project.scripts] in pyproject.toml). This module
assembles the top-level group and registers each subcommand.
"""

from __future__ import annotations

import click

from video_clipping.cli.draft import draft_command
from video_clipping.cli.explain import explain_command
from video_clipping.cli.generate import generate_command
from video_clipping.cli.report import report_command
from video_clipping.cli.spec import spec_group


@click.group()
def cli() -> None:
    """clip — cut highlights from long-form video."""


cli.add_command(draft_command)
cli.add_command(generate_command)
cli.add_command(report_command)
cli.add_command(explain_command)
cli.add_command(spec_group)
