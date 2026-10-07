"""The chat layer is optional: the one-shot CLI must work without it, and nothing outside chat/
may reach agent_shell (import-linter), nor import chat."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

from click.testing import CliRunner

PKG = Path(__file__).resolve().parents[1]
SRC = PKG / "src" / "music_curation"


def lint() -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(Path(sys.executable).parent / "lint-imports")], cwd=PKG, capture_output=True, text=True)


def test_import_contract_passes() -> None:
    r = lint()
    assert r.returncode == 0, r.stdout + r.stderr


def test_a_core_module_importing_agent_shell_or_chat_breaks_the_contract() -> None:
    for name, body in (("_probe_shell.py", "import agent_shell  # noqa\n"),
                       ("_probe_chat.py", "import music_curation.chat.state  # noqa\n")):
        probe = SRC / name
        probe.write_text(body)
        try:
            assert lint().returncode != 0, name
        finally:
            probe.unlink()


NO_EXTRAS = textwrap.dedent("""
    import importlib.abc, sys

    BLOCKED = {"agent_shell", "langgraph", "langchain_anthropic", "langchain_openai", "prompt_toolkit", "rich"}

    class Block(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path, target=None):
            if name.split(".")[0] in BLOCKED:
                raise ModuleNotFoundError(f"No module named {name!r}", name=name)

    sys.meta_path.insert(0, Block())
    from click.testing import CliRunner
    from music_curation.cli import cli
    import music_curation, music_curation.curation, music_curation.reads, music_curation.seed_ingestion

    for cmd in (["generate", "--help"], ["report", "--help"], ["seed", "ingest", "--help"], ["recall", "--help"]):
        r = CliRunner().invoke(cli, cmd)
        assert r.exit_code == 0, r.output
    r = CliRunner().invoke(cli, ["chat"])
    assert r.exit_code != 0 and "optional libraries" in r.output and "music-curation[chat]" in r.output, r.output
    assert not any(m.split(".")[0] in BLOCKED for m in sys.modules)
    print("ok")
""")


def test_one_shot_commands_work_without_the_chat_libraries() -> None:
    env = {**os.environ, "PRODUCTION_AGENTS_ANTHROPIC_API_KEY": "x", "VOYAGE_API_KEY": "x"}
    r = subprocess.run([sys.executable, "-c", NO_EXTRAS], capture_output=True, text=True, env=env)
    assert r.returncode == 0 and "ok" in r.stdout, r.stdout + r.stderr


def test_chat_help_and_no_terminal() -> None:
    from music_curation.cli import cli

    out = CliRunner().invoke(cli, ["chat", "--help"]).output
    for flag in ("--provider", "--model", "--resume", "--dry-run"):
        assert flag in out
    r = CliRunner().invoke(cli, ["chat"])                      # CliRunner's stdin is not a TTY
    assert r.exit_code != 0 and "interactive terminal" in r.output and "Traceback" not in r.output
