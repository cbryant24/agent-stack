"""Runs the lifecycle scripts as subprocesses: an explicit argument list, a timeout, and the
captured output written to the audit log. Never a shell string, and never an added environment
variable, so TEMPLATE_ID and IMAGE can only ever come from the director's own environment."""

from __future__ import annotations

import asyncio
import os
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPTS_DIR_ENV = "VISUAL_GENERATION_SCRIPTS_DIR"
TAIL = 4000
SECRET_ENV = ("RUNPOD_API_KEY",)


@dataclass
class CommandResult:
    argv: list[str]
    rc: int
    stdout: str
    stderr: str
    seconds: float
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.rc == 0 and not self.timed_out

    @property
    def output(self) -> str:
        return "\n".join(x for x in (self.stdout.strip(), self.stderr.strip()) if x)

    def last_line(self) -> str:
        lines = [ln for ln in self.output.splitlines() if ln.strip()]
        return lines[-1].strip() if lines else ""


def scripts_dir() -> Path:
    """The directory holding `pod` and `comfyui-bootstrap`: the override, else `<repo>/scripts`."""
    override = os.environ.get(SCRIPTS_DIR_ENV)
    if override:
        return Path(override)
    for parent in Path(__file__).resolve().parents:
        if (parent / "scripts" / "pod").is_file():
            return parent / "scripts"
    raise FileNotFoundError(
        f"scripts/pod not found above {Path(__file__).parent}; set {SCRIPTS_DIR_ENV} to the scripts directory"
    )


def env_file() -> Path:
    """The `.env` that `op run` resolves: beside the scripts directory."""
    return scripts_dir().parent / ".env"


def redact(text: str) -> str:
    for name in SECRET_ENV:
        value = os.environ.get(name)
        if value and not value.startswith("op://"):
            text = text.replace(value, "***")
    return text


def show(argv: list[str]) -> str:
    """An argv as one readable line (display only; it is never run through a shell)."""
    return " ".join(a if a and " " not in a else repr(a) for a in argv)


class CommandRunner:
    """`audit` receives one record per finished command (the chat passes its session's audit log)."""

    def __init__(self, audit: Callable[..., None] | None = None) -> None:
        self._audit = audit or (lambda **fields: None)

    async def run(self, argv: list[str], *, timeout: float, label: str) -> CommandResult:
        started = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, start_new_session=True,
            )
        except (FileNotFoundError, PermissionError) as exc:
            result = CommandResult(argv, 127, "", f"{argv[0]}: {exc.strerror or exc}", 0.0)
            self._record(label, result)
            return result
        timed_out = False
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout)
        except TimeoutError:
            timed_out = True
            _kill_group(proc.pid)
            out, err = await proc.communicate()
        except asyncio.CancelledError:
            _kill_group(proc.pid)
            raise
        result = CommandResult(
            argv, proc.returncode if proc.returncode is not None else -1,
            redact(out.decode(errors="replace")), redact(err.decode(errors="replace")),
            time.monotonic() - started, timed_out,
        )
        if timed_out:
            result.stderr = (result.stderr + f"\ntimed out after {timeout:.0f}s; the process was killed").strip()
        self._record(label, result)
        return result

    async def spawn(self, argv: list[str], *, log_path: Path, label: str) -> asyncio.subprocess.Process:
        """Start a long-lived process (the tunnel, `pod watch`) detached from this terminal."""
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "ab") as log:
            proc = await asyncio.create_subprocess_exec(
                *argv, stdin=asyncio.subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True,
            )
        self._audit(kind="subprocess", label=label, argv=argv, spawned=True, pid=proc.pid, log=str(log_path))
        return proc

    def _record(self, label: str, r: CommandResult) -> None:
        fields: dict[str, Any] = {
            "kind": "subprocess", "label": label, "argv": r.argv, "rc": r.rc,
            "seconds": round(r.seconds, 2), "timed_out": r.timed_out,
            "stdout": r.stdout[-TAIL:], "stderr": r.stderr[-TAIL:],
        }
        self._audit(**fields)


def _kill_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
