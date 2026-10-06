from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
FORBIDDEN = ("claude-agent-sdk", "openai-agents", "langchain", "langgraph", "anthropic", "openai")


def test_import_linter_contract_passes() -> None:
    lint = Path(sys.executable).parent / "lint-imports"
    r = subprocess.run([str(lint)], cwd=PKG, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_import_linter_actually_catches_a_violation(tmp_path: Path) -> None:
    """Guard against a contract that silently checks nothing."""
    bad = PKG / "src" / "agent_shell" / "_violation_probe.py"
    bad.write_text("import anthropic  # noqa\n")
    try:
        lint = Path(sys.executable).parent / "lint-imports"
        r = subprocess.run([str(lint)], cwd=PKG, capture_output=True, text=True)
        assert r.returncode != 0
    finally:
        bad.unlink()


def test_declared_dependencies_are_vendor_free() -> None:
    deps = tomllib.loads((PKG / "pyproject.toml").read_text())["project"]["dependencies"]
    names = [d.split(">")[0].split("=")[0].strip().lower() for d in deps]
    assert "agent-runtime" in names
    assert not [n for n in names if any(n.startswith(f) for f in FORBIDDEN)]
