from __future__ import annotations

from typing import Callable

from agent_runtime.exceptions import DelegationError

_registry: dict[str, Callable] = {}


def register_agent(name: str, handler: Callable | None = None) -> Callable:
    def _register(fn: Callable) -> Callable:
        if name in _registry:
            raise ValueError(f"Agent '{name}' is already registered")
        _registry[name] = fn
        return fn

    if handler is not None:
        return _register(handler)
    return _register


def get_agent(name: str) -> Callable:
    if name not in _registry:
        raise DelegationError(name, f"No agent registered with name '{name}'")
    return _registry[name]


def list_agents() -> list[str]:
    return list(_registry.keys())


def _clear_registry() -> None:
    _registry.clear()
