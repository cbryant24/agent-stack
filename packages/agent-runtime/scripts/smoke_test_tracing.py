"""Smoke test: sends a few traced spans to Jaeger. Run with:
    uv run python packages/agent-runtime/scripts/smoke_test_tracing.py
Then open http://localhost:16686 and look for service "agent-runtime-smoke".
"""
import asyncio
import os

os.environ.setdefault("PRODUCTION_AGENTS_ANTHROPIC_API_KEY", "sk-test")
os.environ.setdefault("VOYAGE_API_KEY", "pa-test")

from agent_runtime.tracing.setup import init_tracing
from agent_runtime.tracing.decorators import traced, span, record_llm_call


init_tracing("agent-runtime-smoke")


@traced()
def compute_embedding(text: str) -> list[float]:
    return [0.1, 0.2, 0.3]


@traced(name="search.vector_store")
async def search_memory(query: str) -> list[str]:
    await asyncio.sleep(0.01)
    return ["result-1", "result-2"]


async def main() -> None:
    compute_embedding("hello world")

    results = await search_memory("python async patterns")

    with span("report.generate") as s:
        s.set_attribute("results.count", len(results))
        record_llm_call("claude-sonnet-4-6", 512, 1024, 0.018)

    print("Traces sent. Check Jaeger at http://localhost:16686")
    print('Select service "agent-runtime-smoke" and click "Find Traces".')

    # Give the batch exporter time to flush
    await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
