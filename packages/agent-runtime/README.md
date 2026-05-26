# agent-runtime

Shared infrastructure library for the agent-stack workspace. All agent packages import from here. No business logic — only general-purpose primitives for building agents.

## What it provides

**Config** — `RuntimeConfig` / `get_config()` — reads all env vars from `.env`, validates, and creates required directories.

**Models** — `BudgetEnvelope`, `BudgetConsumption`, `DelegationResult`, `TraceEvent` and supporting types. Pydantic v2 throughout.

**Tracing** — `@traced` decorator and `span()` context manager for OTel spans. `record_llm_call / record_tool_call / record_memory_*` helpers attach structured attributes to the current span. `TracePersister` writes a parallel JSONL trace to disk for offline reporting.

**Budget** — `BudgetTracker` (async context manager) enforces per-run cost, item, and wall-time limits. Raises `BudgetExhaustedError` on violation. Tracks cost via a hardcoded pricing table for supported Claude models.

**Delegation** — `register_agent / get_agent` registry + `delegate()` async function. Derives child budget from parent, enforces depth limits, and maps outcomes to `DelegationResult` (completed / partial / failed). Parent budget is automatically debited via contextvar.

**Memory** — Qdrant-backed vector store (`MemoryStore`), Voyage AI embeddings (`EmbeddingClient`, model `voyage-3-large`), and a tiktoken-based chunker (`chunk_document`) with paragraph/sentence-aware splitting and overlap.

**Reporting** — `render_run_report()` renders a Jinja2 Markdown report from the persisted trace and writes it to the Obsidian vault. `notify*` helpers fire macOS notifications.

## Public API

```python
# Config
from agent_runtime import get_config, RuntimeConfig, reset_config

# Models
from agent_runtime import (
    BudgetEnvelope, BudgetMode, BudgetConsumption, BudgetRemaining,
    DelegationRequest, DelegationResult, TraceEvent,
)

# Exceptions
from agent_runtime import BudgetExhaustedError, DelegationError, ConfigurationError

# Tracing
from agent_runtime import init_tracing, traced, span
from agent_runtime import record_llm_call, record_tool_call, record_delegation
from agent_runtime import record_memory_query, record_memory_write
from agent_runtime import TracePersister, load_trace

# Budget & delegation
from agent_runtime import BudgetTracker, register_agent, get_agent, delegate

# Memory
from agent_runtime import (
    MemoryStore, get_memory_store,
    EmbeddingClient, get_embedding_client,
    MemoryPoint, SearchResult,
    chunk_document, chunk_document_with_structure,
)

# Reporting
from agent_runtime import render_run_report, notify, notify_budget_threshold, notify_run_complete
```

## Hello world (20-line example)

```python
import asyncio, os
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-...")
os.environ.setdefault("VOYAGE_API_KEY", "pa-...")

from agent_runtime import (
    BudgetEnvelope, BudgetTracker, register_agent, delegate, init_tracing,
)

init_tracing("hello-world")

@register_agent("echo")
async def echo_agent(request: dict, budget: BudgetEnvelope) -> dict:
    return {"echo": request.get("message", "")}

async def main():
    envelope = BudgetEnvelope(max_depth=1, max_cost_usd=1.0)
    async with BudgetTracker(envelope, "orchestrator") as tracker:
        result = await delegate("echo", {"message": "hello"}, envelope, parent_tracker=tracker)
        print(result.status, result.result)

asyncio.run(main())
```

## Running tests

```bash
# From workspace root
uv run pytest packages/agent-runtime/ -v

# Layer-by-layer
uv run pytest packages/agent-runtime/tests/test_models.py packages/agent-runtime/tests/test_config.py -v
uv run pytest packages/agent-runtime/tests/test_tracing.py -v
uv run pytest packages/agent-runtime/tests/test_budget.py packages/agent-runtime/tests/test_delegation.py -v
uv run pytest packages/agent-runtime/tests/test_memory.py -v      # requires Qdrant
uv run pytest packages/agent-runtime/tests/test_reporting.py -v
```

Qdrant tests are automatically skipped if Qdrant is not running on `localhost:6333`.
