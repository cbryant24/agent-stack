"""Where the pod meets the REPL's life cycle: the startup check, the prompt when a batch drains,
the warning while a pod is up during review, the idle check-in (in place of `pod watch`), and the
question at exit. The risk all of these answer is a pod left billing with nobody watching."""

from __future__ import annotations

import os
import time
from typing import Any

from agent_shell.config import ShellHooks

from visual_generation.chat.pod import lifecycle as lc
from visual_generation.chat.pod.rebuild import run_rebuild
from visual_generation.chat.state import ChatState

# Same names and defaults as scripts/pod's watchdog.
CHECKIN_INTERVAL = float(os.environ.get("CHECKIN_INTERVAL") or 1800)
GRACE = float(os.environ.get("GRACE") or 180)
REVIEW_WARNING_EVERY = 300.0
POSTPONE = 60.0

REVIEW_RULE = "The repo rule is not to leave a pod running during review."
POD_HELP = """\
/pod status                pods on the account and what this session has set up
/pod rebuild               the ten-step pod rebuild runbook; resumes at the first step not passed
/pod rebuild status        where the runbook stands
/pod rebuild restart       forget the checkpoints and start at step 1"""


class PodHooks:
    """`clock` is injectable so tests can move time."""

    def __init__(self, state: ChatState, *, clock: Any = time.monotonic) -> None:
        self.state, self.clock = state, clock

    def shell_hooks(self) -> ShellHooks:
        return ShellHooks(on_start=self.on_start, on_turn_end=self.on_turn_end, on_exit=self.on_exit,
                          idle_due_in=self.idle_due_in, on_idle=self.checkin)

    # startup -----------------------------------------------------------------

    async def on_start(self, ui: Any) -> None:
        pods, r = await lc.status(self.state)
        if not r.ok:
            ui.say(f"pod status unavailable ({r.last_line() or f'rc {r.rc}'}); carrying on without it")
            return
        live = await lc.track(self.state, pods)
        if live is None:
            return
        pod = self.state.pod
        pod.last_checkin = self.clock()
        ui.say(f"A pod is already running: {pod.describe()}. It is billing now. "
               "Run pod_tunnel to reconnect, or pod_down to delete it.")

    # after each turn ---------------------------------------------------------

    async def on_turn_end(self, ui: Any) -> None:
        pod = self.state.pod
        if not pod.up:
            return
        if pod.last_checkin is None:
            pod.last_checkin = self.clock()
        if pod.drain_pending:
            pod.drain_pending = False
            answer = await ui.choose(
                f"Batch drained. Export artifacts and delete the pod now? ({pod.describe()})",
                {"y": "export and delete", "n": "keep the pod up"})
            if answer == "y":
                await self.export_and_delete(ui)
            else:
                pod.last_review_warning = self.clock()
                ui.say(f"Pod stays up while you review. {REVIEW_RULE}")
            return
        if self.idle_due_in() == 0.0:
            await self.checkin(ui)
            return
        last = pod.last_review_warning
        if pod.rendered and not pod.in_flight and (last is None or self.clock() - last >= REVIEW_WARNING_EVERY):
            pod.last_review_warning = self.clock()
            ui.say(f"Pod is up while you review: {pod.describe()}. {REVIEW_RULE}")

    # idle check-in -----------------------------------------------------------

    def idle_due_in(self) -> float | None:
        pod = self.state.pod
        if not pod.up or pod.last_checkin is None:
            return None
        return max(0.0, pod.last_checkin + CHECKIN_INTERVAL - self.clock())

    async def checkin(self, ui: Any) -> None:
        pod = self.state.pod
        if not pod.up:
            return
        if pod.in_flight:                    # never delete a pod with a render running
            pod.last_checkin = self.clock() - CHECKIN_INTERVAL + POSTPONE
            return
        answer = await ui.choose(
            f"Pod check-in: {pod.describe()}. Still working? No answer in {GRACE / 60:.0f} min exports and deletes it.",
            {"k": "keep it up", "d": "export and delete"}, timeout=GRACE)
        if answer == "k":
            pod.last_checkin = self.clock()
            return
        if answer is None:
            ui.say(f"No answer in {GRACE / 60:.0f} min: exporting, then deleting the pod, as scripts/pod watch would.")
        await self.export_and_delete(ui, attended=answer is not None)

    # exit --------------------------------------------------------------------

    async def on_exit(self, ui: Any) -> None:
        pod = self.state.pod
        if not pod.up:
            return
        options = {"d": "export and delete"}
        if lc.can_watch():
            options["w"] = "leave it up, start scripts/pod watch"
        options["l"] = "leave it up"
        answer = await ui.choose(f"A pod is still running: {pod.describe()}. It keeps billing after you exit.", options)
        if answer == "d":
            await self.export_and_delete(ui)
        elif answer == "w":
            log = await lc.start_watch(self.state)
            ui.say(f"scripts/pod watch started; it asks every {CHECKIN_INTERVAL / 60:.0f} min and deletes the pod "
                   f"if nobody answers. Log: {log}")
        else:
            ui.say("Pod left running with no watchdog. Delete it with: ./scripts/pod down")
        await lc.stop_tunnel(self.state)

    # shared ------------------------------------------------------------------

    async def export_and_delete(self, ui: Any, *, attended: bool = True) -> None:
        """Export, then delete. The director's answer (or their silence at a check-in) is the
        confirmation, so pod_down skips the gate; dry-run and the audit log still apply."""
        exported = await ui.run_tool("export_artifacts")
        if exported.is_error and attended:
            ui.say("The export reported problems, so the pod was NOT deleted. It is still billing: "
                   "fix the export or run pod_down.")
            return
        await ui.run_tool("pod_down", confirmed=True)

    # /pod --------------------------------------------------------------------

    async def slash(self, args: list[str], ui: Any) -> str:
        if args[:1] == ["status"]:
            return (await ui.session.run_tool("pod_status")).text
        if args[:1] == ["rebuild"]:
            return await run_rebuild(self.state, ui, args[1:])
        return "usage: /pod status | /pod rebuild [status|restart]"
