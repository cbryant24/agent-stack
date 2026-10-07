"""What a hook or an agent slash command can do to the front end.

The REPL implements this with the terminal; `ScriptedUI` implements it with canned answers, so
agent code that asks questions can be tested with no terminal.
"""

from __future__ import annotations

from typing import Any, Protocol

from agent_shell.guard.gate import ConfirmRequest, Decision, DecisionKind
from agent_shell.tools.registry import ToolResult


class ShellUI(Protocol):
    session: Any

    def say(self, text: str) -> None: ...

    async def ask(self, request: ConfirmRequest) -> Decision: ...

    async def choose(
        self, prompt: str, options: dict[str, str], *, timeout: float | None = None
    ) -> str | None:
        """One key of `options` (key -> label), or None if `timeout` passed with no answer."""
        ...

    async def run_tool(
        self, name: str, args: dict[str, Any] | None = None, *, confirmed: bool = False
    ) -> ToolResult: ...


class ScriptedUI:
    """A ShellUI with scripted answers. `choices` answer `choose` in order (None = no answer in
    time); `decisions` answer gate confirmations in order (default: reject)."""

    def __init__(
        self, session: Any, *, choices: list[str | None] | None = None,
        decisions: list[Decision | DecisionKind] | None = None,
    ) -> None:
        self.session = session
        self.choices = list(choices or [])
        self.decisions = [Decision(kind=d) if isinstance(d, str) else d for d in (decisions or [])]
        self.said: list[str] = []
        self.asked: list[str] = []
        self.requests: list[ConfirmRequest] = []

    def say(self, text: str) -> None:
        self.said.append(text)

    async def ask(self, request: ConfirmRequest) -> Decision:
        self.requests.append(request)
        return self.decisions.pop(0) if self.decisions else Decision(kind="reject")

    async def choose(
        self, prompt: str, options: dict[str, str], *, timeout: float | None = None
    ) -> str | None:
        self.asked.append(prompt)
        if not self.choices:
            raise AssertionError(f"unexpected question: {prompt}")
        return self.choices.pop(0)

    async def run_tool(
        self, name: str, args: dict[str, Any] | None = None, *, confirmed: bool = False
    ) -> ToolResult:
        return await self.session.run_tool(name, args, confirmed=confirmed, confirmer=self)
