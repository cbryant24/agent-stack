"""What the chat knows about the pod it is driving. Three checkpoints are tracked apart, because
on 2026-10-07 each failed on its own: ComfyUI installed and started (`bootstrapped`), the SSH
tunnel (`tunnel` / `endpoint`), and the registry synced against this pod (`synced_pod_id`)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

LOCAL_PORT = 8188


@dataclass
class PodInfo:
    pod_id: str
    name: str = ""
    status: str = ""
    gpu_count: int = 0
    cost_per_hr: float | None = None

    @property
    def running(self) -> bool:
        return self.status == "RUNNING" and self.gpu_count >= 1


@dataclass
class PodSession:
    info: PodInfo | None = None
    started_at: str | None = None              # from the ledger's open entry
    start_observed: bool = True
    ssh_ip: str | None = None
    ssh_port: int | None = None
    bootstrapped: bool = False
    tunnel: asyncio.subprocess.Process | None = None
    endpoint: str | None = None
    synced_pod_id: str | None = None
    synced_at: str | None = None
    rendered: bool = False                     # a render finished on this pod, so its models are warm
    in_flight: bool = False                    # a render is running right now
    generation_ids: list[str] = field(default_factory=list)
    output_paths: list[str] = field(default_factory=list)
    unexported: int = 0                        # renders since the last export
    drain_pending: bool = False
    last_checkin: float | None = None          # monotonic
    last_review_warning: float | None = None   # monotonic
    known_hosts: Path | None = None

    @property
    def pod_id(self) -> str | None:
        return self.info.pod_id if self.info else None

    @property
    def up(self) -> bool:
        return self.info is not None

    @property
    def rate(self) -> float | None:
        return self.info.cost_per_hr if self.info else None

    @property
    def tunnel_alive(self) -> bool:
        return self.tunnel is not None and self.tunnel.returncode is None

    @property
    def synced(self) -> bool:
        return self.up and self.synced_pod_id == self.pod_id

    def uptime_seconds(self) -> float | None:
        if not self.started_at:
            return None
        return max(0.0, (datetime.now(UTC) - datetime.fromisoformat(self.started_at)).total_seconds())

    def cost_so_far(self) -> float | None:
        up, rate = self.uptime_seconds(), self.rate
        return None if up is None or rate is None else up / 3600.0 * rate

    def describe(self) -> str:
        if not self.info:
            return "no pod"
        up, cost = self.uptime_seconds(), self.cost_so_far()
        parts = [self.info.pod_id]
        if up is not None:
            parts.append(("up at least " if not self.start_observed else "up ") + f"{int(up // 60)} min")
        if cost is not None:
            parts.append(f"${cost:.2f} so far")
        elif self.rate is not None:
            parts.append(f"${self.rate:.2f}/hr")
        return ", ".join(parts)

    def forget(self) -> None:
        """The pod is gone: drop everything tied to it (the tunnel is stopped by the caller)."""
        self.info = None
        self.started_at = None
        self.start_observed = True
        self.ssh_ip = self.ssh_port = None
        self.bootstrapped = False
        self.tunnel = None
        self.endpoint = None
        self.rendered = self.in_flight = False
        self.unexported = 0
        self.drain_pending = False
        self.last_checkin = self.last_review_warning = None
