"""The chat layer is optional: the one-shot CLI must work without it, and nothing outside chat/
may reach agent_shell (import-linter), nor import chat."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

from click.testing import CliRunner

PKG = Path(__file__).resolve().parents[1]
SRC = PKG / "src" / "visual_generation"


def lint() -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(Path(sys.executable).parent / "lint-imports")], cwd=PKG, capture_output=True, text=True)


def test_import_contract_passes() -> None:
    r = lint()
    assert r.returncode == 0, r.stdout + r.stderr


def test_a_new_core_module_importing_agent_shell_breaks_the_contract() -> None:
    probe = SRC / "_probe_shell.py"
    probe.write_text("import agent_shell  # noqa\n")
    try:
        assert lint().returncode != 0
    finally:
        probe.unlink()


def test_a_core_module_importing_chat_breaks_the_contract() -> None:
    probe = SRC / "_probe_chat.py"
    probe.write_text("import visual_generation.chat.state  # noqa\n")
    try:
        assert lint().returncode != 0
    finally:
        probe.unlink()


def test_chat_modules_may_use_agent_shell() -> None:
    assert "agent_shell" in (SRC / "chat" / "cli.py").read_text()      # and the contract above still passes


NO_EXTRAS = textwrap.dedent("""
    import importlib.abc, sys

    BLOCKED = {"agent_shell", "langgraph", "langchain_anthropic", "langchain_openai",
               "prompt_toolkit", "rich"}

    class Block(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path, target=None):
            if name.split(".")[0] in BLOCKED:
                raise ModuleNotFoundError(f"No module named {name!r}", name=name)

    sys.meta_path.insert(0, Block())
    from click.testing import CliRunner
    from visual_generation.cli import cli
    import visual_generation.cli

    r = CliRunner().invoke(cli, ["draft", "--help"])
    assert r.exit_code == 0 and "Craft a settled generation spec" in r.output, r.output
    r = CliRunner().invoke(cli, ["recall", "--help"])
    assert r.exit_code == 0, r.output
    r = CliRunner().invoke(cli, ["chat", "--project", "demo"])
    assert r.exit_code != 0 and "optional libraries" in r.output and "visual-generation[chat]" in r.output, r.output
    assert not any(m.split(".")[0] in BLOCKED for m in sys.modules)
    print("ok")
""")


def test_one_shot_commands_work_without_the_chat_libraries() -> None:
    env_keys = {"PRODUCTION_AGENTS_ANTHROPIC_API_KEY": "x", "VOYAGE_API_KEY": "x"}
    import os

    r = subprocess.run([sys.executable, "-c", NO_EXTRAS], capture_output=True, text=True,
                       env={**os.environ, **env_keys})
    assert r.returncode == 0 and "ok" in r.stdout, r.stdout + r.stderr


def test_chat_help_lists_the_documented_options() -> None:
    from visual_generation.cli import cli

    out = CliRunner().invoke(cli, ["chat", "--help"]).output
    for flag in ("--provider", "--model", "--project", "--resume", "--dry-run"):
        assert flag in out
    assert "claude|openai" in out


def test_visual_agent_script_is_registered() -> None:
    import tomllib

    scripts = tomllib.loads((PKG / "pyproject.toml").read_text())["project"]["scripts"]
    assert scripts["visual-agent"] == "visual_generation.cli:chat_entry"
    assert scripts["visual-generation"] == "visual_generation.cli:cli"


def test_chat_without_a_terminal_fails_cleanly() -> None:
    from visual_generation.cli import cli

    r = CliRunner().invoke(cli, ["chat", "--project", "demo"])      # CliRunner's stdin is not a TTY
    assert r.exit_code != 0 and "interactive terminal" in r.output and "Traceback" not in r.output
