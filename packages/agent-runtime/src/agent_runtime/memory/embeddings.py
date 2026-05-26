from __future__ import annotations

from functools import lru_cache
from typing import Literal

import voyageai

from agent_runtime.tracing.decorators import record_tool_call

_VOYAGE_MODEL = "voyage-3-large"
_BATCH_SIZE = 128


class EmbeddingClient:
    def __init__(self, api_key: str) -> None:
        self._client = voyageai.AsyncClient(api_key=api_key)

    async def embed(
        self,
        texts: list[str],
        input_type: Literal["document", "query"] = "document",
    ) -> list[list[float]]:
        if not texts:
            return []

        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), _BATCH_SIZE):
            batch = texts[i : i + _BATCH_SIZE]
            response = await self._client.embed(
                batch,
                model=_VOYAGE_MODEL,
                input_type=input_type,
            )
            all_embeddings.extend(response.embeddings)

        record_tool_call(
            "voyage.embed",
            f"texts={len(texts)}, type={input_type}",
            f"vectors={len(all_embeddings)}, dim={len(all_embeddings[0]) if all_embeddings else 0}",
        )
        return all_embeddings


@lru_cache(maxsize=1)
def get_embedding_client() -> EmbeddingClient:
    from agent_runtime.config import get_config
    return EmbeddingClient(api_key=get_config().voyage_api_key)
