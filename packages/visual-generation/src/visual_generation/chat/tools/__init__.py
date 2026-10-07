from __future__ import annotations

from agent_shell.tools.registry import ToolSpec

from visual_generation.chat.state import ChatState
from visual_generation.chat.tools.craft import make_craft_tools
from visual_generation.chat.tools.generation import make_generation_tools
from visual_generation.chat.tools.interpret import make_interpret_tools
from visual_generation.chat.tools.pod import make_pod_tools
from visual_generation.chat.tools.reads import make_read_tools
from visual_generation.chat.tools.writes import make_write_tools


def tool_pack(state: ChatState) -> list[ToolSpec]:
    """Every tool the chat exposes: reads, craft, interpret, the confirmed writes, and (Phase 5) the
    generation and pod tools. Every write and every spend goes through the gate."""
    return [
        *make_read_tools(state), *make_craft_tools(state), *make_interpret_tools(state),
        *make_write_tools(state), *make_generation_tools(state), *make_pod_tools(state),
    ]
