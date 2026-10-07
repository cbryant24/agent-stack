from __future__ import annotations

from agent_shell.packs.knowledge import knowledge_tools
from agent_shell.tools.registry import ToolSpec

from music_curation.chat.state import ChatState
from music_curation.chat.tools.craft import make_craft_tools
from music_curation.chat.tools.interpret import make_interpret_tools
from music_curation.chat.tools.reads import make_read_tools
from music_curation.chat.tools.seed import make_seed_tools
from music_curation.chat.tools.writes import make_write_tools


def tool_pack(state: ChatState) -> list[ToolSpec]:
    """Every tool the chat exposes: reads, prompt writing, reaction interpretation, the confirmed
    writes, seed import, and the shared knowledge pack. Every write goes through the gate."""
    return [
        *make_read_tools(state), *make_craft_tools(state), *make_interpret_tools(state),
        *make_write_tools(state), *make_seed_tools(state),
        *knowledge_tools(lambda: state.stores()[2]),
    ]
