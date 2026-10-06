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


def test_only_the_engine_module_imports_the_langchain_stack() -> None:
    import ast

    stack = ("langchain", "langchain_core", "langchain_anthropic", "langchain_openai", "langgraph")
    offenders: dict[str, set[str]] = {}
    for path in (PKG / "src" / "agent_shell").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = (
                [a.name for a in node.names] if isinstance(node, ast.Import)
                else [node.module or ""] if isinstance(node, ast.ImportFrom) and node.level == 0
                else []
            )
            for n in names:
                if n.split(".")[0] in stack:
                    offenders.setdefault(str(path.relative_to(PKG / "src" / "agent_shell")), set()).add(n)
    assert set(offenders) == {"engine/langgraph_engine.py"}, offenders


def test_importing_the_core_does_not_load_langgraph_or_the_model_libraries() -> None:
    """langchain_core is excluded on purpose: agent-runtime's text splitter already loads it."""
    code = (
        "import sys, agent_shell.session.api, agent_shell.repl.app, agent_shell.engine.factory, "
        "agent_shell.demo; "
        "bad = [m for m in sys.modules if m.split('.')[0] in "
        "('langgraph','langchain_anthropic','langchain_openai')]; "
        "sys.exit(1 if bad else 0)"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_a_langgraph_import_outside_the_engine_module_breaks_the_contract() -> None:
    bad = PKG / "src" / "agent_shell" / "_langgraph_probe.py"
    bad.write_text("import langgraph  # noqa\n")
    try:
        lint = Path(sys.executable).parent / "lint-imports"
        r = subprocess.run([str(lint)], cwd=PKG, capture_output=True, text=True)
        assert r.returncode != 0
    finally:
        bad.unlink()
