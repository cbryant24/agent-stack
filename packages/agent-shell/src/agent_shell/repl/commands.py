from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from agent_shell.engine.base import Engine
from agent_shell.session.api import Session
from agent_shell.ui import ShellUI

COMMANDS = [
    "/help", "/exit", "/cost", "/budget", "/dry-run", "/tools", "/audit",
    "/session", "/provider", "/model",
]

HELP = """\
/help                      this list
/exit                      end the session (then review proposed writes)
/cost                      spend so far, per budget
/budget                    limits and what is left
/dry-run [on|off]          gated tools describe what they would do and run nothing
/tools                     tools and their effect class
/audit                     last tool calls from the audit log
/session list              recent sessions
/session resume <id>       switch to an earlier session
/session rename <title>    name this session
/provider [name] [model]   show or switch the engine provider (history carries over)
/model [name]              show or change the model (history carries over)"""


@dataclass
class SlashResult:
    output: str = ""
    exit: bool = False
    resume_id: str | None = None


EngineFactory = Callable[[str, str | None], Engine]


class ReplContext:
    """`engines` are ready-made engines by provider name; `engine_factory(provider, model)`
    builds one on demand (and may raise `EngineConfigError`-style errors with a clear message)."""

    def __init__(
        self,
        session: Session,
        engines: Mapping[str, Engine] | None = None,
        engine_factory: EngineFactory | None = None,
        ui: ShellUI | None = None,
    ) -> None:
        self.session = session
        self.ui = ui            # what an agent's own slash command talks through
        self.engines: dict[str, Engine] = dict(engines or {})
        self.engine_factory = engine_factory

    def build(self, provider: str, model: str | None) -> Engine | str:
        """An engine, or a message saying why not."""
        if provider in self.engines and model is None:
            return self.engines[provider]
        if self.engine_factory is None:
            return f"unknown provider: {provider}" if provider not in self.engines else "no factory"
        try:
            return self.engine_factory(provider, model)
        except Exception as e:  # noqa: BLE001 - shown to the user, session stays as it was
            return f"{type(e).__name__}: {e}"


def _money(v: float | None) -> str:
    return "unlimited" if v is None else f"${v:.4f}"


async def handle_slash(line: str, ctx: ReplContext) -> SlashResult:
    """Local commands: no LLM call is made."""
    parts = line.strip().split()
    cmd, args = parts[0], parts[1:]
    s = ctx.session

    if cmd == "/help":
        extra = s.config.slash_help
        return SlashResult(HELP + ("\n" + extra if extra else ""))
    if cmd == "/exit":
        return SlashResult(exit=True)
    if cmd == "/cost":
        rows = [f"{n}: ${b['spent']:.4f}" for n, b in s.budgets.summary().items()]
        return SlashResult("spent  " + "   ".join(rows))
    if cmd == "/budget":
        rows = [
            f"{b.name}: {_money(b.remaining)} left of {_money(b.max_usd)}"
            for b in (s.budgets.repl, s.budgets.tool, s.budgets.gpu)
        ]
        return SlashResult("\n".join(rows))
    if cmd == "/dry-run":
        if args and args[0] in ("on", "off"):
            s.dry_run = args[0] == "on"
        elif args:
            return SlashResult("usage: /dry-run [on|off]")
        return SlashResult(f"dry-run is {'on' if s.dry_run else 'off'}")
    if cmd == "/tools":
        return SlashResult("\n".join(f"{t.name:<28} {t.effect.value:<18} {t.description}" for t in s.registry))
    if cmd == "/audit":
        recs = [r for r in (s.audit.read() if s.audit else []) if r.get("kind", "tool_call") == "tool_call"][-10:]
        if not recs:
            return SlashResult("no tool calls yet")
        return SlashResult("\n".join(
            f"{r['ts'][11:19]} {r['tool']} [{r['decision']}] {json.dumps(r['args'])[:80]}"
            for r in recs
        ))
    if cmd == "/session":
        return _session(args, ctx)
    if cmd == "/provider":
        if not args:
            avail = sorted({*ctx.engines, "claude", "openai"}) if ctx.engine_factory else sorted(ctx.engines)
            return SlashResult(
                f"provider: {s.engine.provider}  model: {s.engine.model}  "
                f"(available: {', '.join(avail) or 'this one only'})"
            )
        built = ctx.build(args[0], args[1] if len(args) > 1 else None)
        if isinstance(built, str):
            return SlashResult(built)
        await s.switch_engine(built)
        return SlashResult(f"provider: {built.provider} ({built.model}); history carried over")
    if cmd == "/model":
        if not args:
            return SlashResult(f"model: {s.engine.model}")
        if ctx.engine_factory is None:
            s.engine.model = args[0]
            return SlashResult(f"model: {s.engine.model}")
        built = ctx.build(s.engine.provider, args[0])
        if isinstance(built, str):
            return SlashResult(built)
        await s.switch_engine(built)
        return SlashResult(f"model: {built.model}; history carried over")
    agent_cmd = s.config.slash_commands.get(cmd)
    if agent_cmd is not None:
        if ctx.ui is None:
            return SlashResult(f"{cmd} needs an interactive front end")
        try:
            return SlashResult(await agent_cmd(args, ctx.ui) or "")
        except Exception as e:  # noqa: BLE001 - shown to the user, the session carries on
            return SlashResult(f"{type(e).__name__}: {e}")
    return SlashResult(f"unknown command: {cmd} (try /help)")


def _session(args: list[str], ctx: ReplContext) -> SlashResult:
    s = ctx.session
    sub = args[0] if args else "list"
    if sub == "list":
        rows = s.store.list(s.config.agent_name)
        return SlashResult("\n".join(
            f"{r.id}  {r.updated_at[:19]}  {r.provider}/{r.model}  {r.title}" for r in rows
        ) or "no sessions")
    if sub == "resume" and len(args) == 2:
        if not s.store.exists(args[1]):
            return SlashResult(f"unknown session: {args[1]}")
        return SlashResult(f"resuming {args[1]}", resume_id=args[1])
    if sub == "rename" and len(args) > 1:
        s.store.rename(s.session_id, " ".join(args[1:]))
        return SlashResult("renamed")
    return SlashResult("usage: /session list | resume <id> | rename <title>")
