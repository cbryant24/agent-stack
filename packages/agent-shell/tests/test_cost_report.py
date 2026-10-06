from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from agent_shell.engine.fake import Call, FakeEngine, Say
from agent_shell.session.api import Session
from agent_shell.testing import drain

pytestmark = pytest.mark.asyncio
REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "agent_costs.py"


def report(data_dir: Path, *args: str) -> str:
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--data-dir", str(data_dir), *args],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout


async def test_by_session_rolls_up_a_shell_session_across_segments_and_providers(
    make_session: Callable[..., Session], settings
) -> None:  # type: ignore[no-untyped-def]
    a = FakeEngine([[Say(text="one", cost_usd=0.10)]])
    s1 = make_session(engine=a)
    await s1.start()
    await drain(s1, "first")
    other = FakeEngine()
    other.provider = "claude"
    other.script = [[Say(text="skip")], [Say(text="two", cost_usd=0.25)]]  # resumes at turn 2
    await s1.switch_engine(other)
    await drain(s1, "second")
    sid = s1.session_id
    await s1.close()

    script: list[list[Say | Call]] = [
        [Say(text="skip")], [Say(text="skip")], [Say(text="three", cost_usd=0.01)]
    ]
    s2 = make_session(engine=FakeEngine(script))
    await s2.start(resume_id=sid)
    await drain(s2, "third")
    await s2.close()

    out = report(settings.agent_data_dir, "--agent", "t", "--by-session")
    row = next(line for line in out.splitlines() if line.startswith(sid[:26]))
    assert "$0.3600" in row                      # 0.10 + 0.25 + 0.01 across 2 segments
    assert "claude,fake" in row
    assert row.split()[1] == "3"                 # three user turns, not two trace segments
    assert "1 sessions" in out


async def test_by_session_still_works_for_old_orchestrator_style_traces(tmp_path: Path) -> None:
    d = tmp_path / "runs" / "2026-01-01" / "orchestrator" / "r1"
    d.mkdir(parents=True)
    (d / "trace.jsonl").write_text(
        '{"event_type":"info","timestamp":"2026-01-01T00:00:00","metadata":{"event":"run_end",'
        '"status":"completed","envelope":{"session_id":"thread-9"},'
        '"summary":{"cost_usd":0.5,"llm_calls":2,"tool_calls":1}}}\n'
    )
    out = report(tmp_path, "--by-session")
    row = next(line for line in out.splitlines() if line.startswith("thread-9"))
    assert "$0.5000" in row and row.split()[1] == "1"
