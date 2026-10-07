from __future__ import annotations

from agent_shell.tools.registry import ToolSpec

from visual_generation.chat.state import ChatState
from visual_generation.chat.tools.craft import make_craft_tools
from visual_generation.chat.tools.interpret import make_interpret_tools
from visual_generation.chat.tools.reads import make_read_tools
from visual_generation.chat.tools.writes import make_write_tools


def tool_pack(state: ChatState) -> list[ToolSpec]:
    """Every tool the chat exposes: reads, craft, interpret, and the confirmed writes. Nothing that
    renders on a GPU (a reachability test enforces it); every write goes through the gate."""
    return [
        *make_read_tools(state), *make_craft_tools(state), *make_interpret_tools(state),
        *make_write_tools(state),
    ]
