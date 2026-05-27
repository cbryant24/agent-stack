from __future__ import annotations

import asyncio


async def search_for_tutorials(topic: str, max_results: int = 20) -> list[str]:
    from tavily import TavilyClient

    from agent_runtime import get_config

    api_key = get_config().tavily_api_key
    if not api_key:
        raise ValueError("TAVILY_API_KEY is not configured")

    client = TavilyClient(api_key=api_key)
    results = await asyncio.to_thread(
        client.search,
        query=f"YouTube tutorial {topic}",
        search_depth="basic",
        include_domains=["youtube.com"],
        max_results=max_results,
    )

    urls = [
        r["url"]
        for r in results.get("results", [])
        if "youtube.com/watch" in r.get("url", "")
    ]
    return urls
