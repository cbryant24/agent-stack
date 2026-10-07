from __future__ import annotations

from pathlib import Path

from agent_runtime.models import BudgetEnvelope
from agent_shell.config import ChatConfig

from visual_generation.chat.pod.hooks import POD_HELP, PodHooks
from visual_generation.chat.state import ChatState
from visual_generation.chat.tools import tool_pack

AGENT_NAME = "visual-generation"
PROMPT_PATH = Path(__file__).parent / "prompts" / "system.md"


def system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def build_chat_config(state: ChatState) -> ChatConfig:
    """The ChatConfig agent-shell needs. The system prompt is static (byte-stable, so provider
    prefix caching works); project state rides in the tool descriptions, set once per session."""
    pod_hooks = PodHooks(state)
    return ChatConfig(
        agent_name=AGENT_NAME,
        system_prompt=system_prompt(),
        tool_pack=lambda: tool_pack(state),
        default_budget=BudgetEnvelope(max_cost_usd=1.0, max_depth=1),
        # Anything proposed but not written by /exit is offered again (accepted ones are applied
        # through their tool; deferred ones queue under drafts/visual-generation/).
        on_session_end=lambda transcript: state.unwritten_proposals(),
        # Pod safety: startup check, drain prompt, idle check-in, exit question, and /pod.
        hooks=pod_hooks.shell_hooks(),
        slash_commands={"/pod": pod_hooks.slash},
        slash_help=POD_HELP,
    )
