from __future__ import annotations

from agent_shell.tools.registry import Registry


def export_mcp_server(registry: Registry) -> None:
    """Expose a registry as an MCP server (not built yet).

    Left as a stub on purpose: the `mcp` package is not a dependency of agent-runtime, and
    this phase adds no new runtime dependency. When it is built, every MCP call must still
    go through `Executor.run`, so the gate and audit log apply.
    """
    raise NotImplementedError(
        "mcp_export is a stub: add the `mcp` dependency in a later phase "
        "and route calls through Executor.run"
    )
