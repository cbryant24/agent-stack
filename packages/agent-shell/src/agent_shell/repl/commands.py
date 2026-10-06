from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

from agent_shell.engine.base import Engine
from agent_shell.session.api import Session

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
/provider [name]           show or switch the engine provider
/model [name]              show or change the model"""


@dataclass
class SlashResult:
    output: str = ""
    exit: bool = False
    resume_id: str | None = None


class ReplContext:
    def __init__(self, session: Session, engines: Mapping[str, Engine] | None = None) -> None:
        self.session = session
        self.engines: dict[str, Engine] = dict(engines or {})


def _money(v: float | None) -> str:
    return "unlimited" if v is None else f"${v:.4f}"


async def handle_slash(line: str, ctx: ReplContext) -> SlashResult:
    """Local commands: no LLM call is made."""
    parts = line.strip().split()
    cmd, args = parts[0], parts[1:]
    s = ctx.session

    if cmd == "/help":
        return SlashResult(HELP)
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
        recs = s.audit.read()[-10:] if s.audit else []
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
            return SlashResult(f"provider: {s.engine.provider}  (available: {', '.join(sorted(ctx.engines)) or 'this one only'})")
        eng = ctx.engines.get(args[0])
        if eng is None:
            return SlashResult(f"unknown provider: {args[0]}")
        await _switch_engine(s, eng)
        return SlashResult(f"provider: {eng.provider} ({eng.model})")
    if cmd == "/model":
        if args:
            s.engine.model = args[0]
        return SlashResult(f"model: {s.engine.model}")
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


async def _switch_engine(session: Session, engine: Engine) -> None:
    """Close the current engine handle and restart this session on `engine`."""
    sid = session.session_id
    await session.close()
    session.engine = engine
    await session.start(resume_id=sid)
