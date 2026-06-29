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
    record_delegation_decision,
    record_llm_call,
    record_memory_query,
    record_memory_write,
    record_tool_call,
    span,
    traced,
)
from agent_runtime.budget import BudgetTracker
from agent_runtime.diagnostics import (
    DiagnosticReport,
    RemediationOutcome,
    RemediationSpec,
    Status,
)
from agent_runtime.registry import get_agent, list_agents, register_agent
from agent_runtime.delegation import delegate
from agent_runtime.memory import (
    EmbeddingClient,
    MemoryPoint,
    MemoryStore,
    MultimodalInput,
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
from agent_runtime.knowledge import (
    DocCandidate,
    Draft,
    KnowledgeEntry,
    KnowledgeHit,
    UserKnowledgeStore,
    ingest_docs,
    ingest_docs_sync,
    parse_docs,
)
from agent_runtime.llm import LLMCompletion, LLMProvider, get_provider

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
    "record_delegation_decision",
    "record_memory_query",
    "record_memory_write",
    "TracePersister",
    "load_trace",
    # budget
    "BudgetTracker",
    # diagnostics (shared cross-package types)
    "DiagnosticReport",
    "RemediationSpec",
    "RemediationOutcome",
    "Status",
    # registry & delegation
    "register_agent",
    "get_agent",
    "list_agents",
    "delegate",
    # memory
    "MemoryPoint",
    "SearchResult",
    "EmbeddingClient",
    "MultimodalInput",
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
    # knowledge
    "UserKnowledgeStore",
    "Draft",
    "KnowledgeEntry",
    "KnowledgeHit",
    "DocCandidate",
    "parse_docs",
    "ingest_docs",
    "ingest_docs_sync",
    # llm provider seam
    "LLMProvider",
    "LLMCompletion",
    "get_provider",
]
