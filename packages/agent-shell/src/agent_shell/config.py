from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agent_runtime.models import BudgetEnvelope

from agent_shell.proposals import Proposal
from agent_shell.tools.registry import ToolSpec


class ChatConfig(BaseModel):
    """What an agent supplies to opt in to a chat shell."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    agent_name: str
    system_prompt: str
    tool_pack: Callable[[], list[ToolSpec]]
    default_budget: BudgetEnvelope
    on_session_end: Callable[..., list[Proposal]] | None = None


class ShellSettings(BaseModel):
    """Per-session knobs; paths derive from the runtime's agent_data_dir."""

    agent_data_dir: Path
    dry_run: bool = False
    repl_budget_usd: float = Field(default=1.0, ge=0)
    tool_budget_usd: float = Field(default=0.5, ge=0)
    gpu_budget_usd: float = Field(default=0.0, ge=0)

    @property
    def db_path(self) -> Path:
        return self.agent_data_dir / "agent-stack.db"

    def drafts_dir(self, agent: str) -> Path:
        return self.agent_data_dir / "drafts" / agent
