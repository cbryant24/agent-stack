__version__ = "0.0.1"

from agent_runtime.config import RuntimeConfig, get_config, reset_config
from agent_runtime.exceptions import (
    AgentRuntimeError,
    BudgetExhaustedError,
    ConfigurationError,
    DelegationError,
)
from agent_runtime.models import (
    BudgetConsumption,
    BudgetEnvelope,
    BudgetMode,
    BudgetRemaining,
    DelegationRequest,
    DelegationResult,
    TraceEvent,
)
from agent_runtime.tracing import (
    TracePersister,
    init_tracing,
    load_trace,
    record_delegation,
    record_llm_call,
    record_memory_query,
    record_memory_write,
    record_tool_call,
    span,
    traced,
)
from agent_runtime.budget import BudgetTracker
from agent_runtime.registry import get_agent, list_agents, register_agent
from agent_runtime.delegation import delegate
from agent_runtime.memory import (
    EmbeddingClient,
    MemoryPoint,
    MemoryStore,
    SearchResult,
    chunk_document,
    chunk_document_with_structure,
    get_embedding_client,
    get_memory_store,
)
from agent_runtime.reporting import (
    notify,
    notify_budget_threshold,
    notify_run_complete,
    render_run_report,
)

__all__ = [
    "__version__",
    # config
    "RuntimeConfig",
    "get_config",
    "reset_config",
    # exceptions
    "AgentRuntimeError",
    "BudgetExhaustedError",
    "ConfigurationError",
    "DelegationError",
    # models
    "BudgetConsumption",
    "BudgetEnvelope",
    "BudgetMode",
    "BudgetRemaining",
    "DelegationRequest",
    "DelegationResult",
    "TraceEvent",
    # tracing
    "init_tracing",
    "traced",
    "span",
    "record_llm_call",
    "record_tool_call",
    "record_delegation",
    "record_memory_query",
    "record_memory_write",
    "TracePersister",
    "load_trace",
    # budget
    "BudgetTracker",
    # registry & delegation
    "register_agent",
    "get_agent",
    "list_agents",
    "delegate",
    # memory
    "MemoryPoint",
    "SearchResult",
    "EmbeddingClient",
    "get_embedding_client",
    "MemoryStore",
    "get_memory_store",
    "chunk_document",
    "chunk_document_with_structure",
    # reporting
    "render_run_report",
    "notify",
    "notify_budget_threshold",
    "notify_run_complete",
]
