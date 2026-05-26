from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import voyageai
from pydantic import BaseModel, model_validator

from agent_runtime.tracing.decorators import record_tool_call

_VOYAGE_MODEL = "voyage-3-large"
_VOYAGE_MULTIMODAL_MODEL = "voyage-multimodal-3"
_BATCH_SIZE = 128
_MULTIMODAL_BATCH_SIZE = 10

_SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


class MultimodalInput(BaseModel):
    text: str | None = None
    image_path: Path | None = None

    @model_validator(mode="after")
    def _validate(self) -> MultimodalInput:
        if self.text is None and self.image_path is None:
            raise ValueError("At least one of text or image_path must be provided")
        if self.image_path is not None:
            if not self.image_path.exists():
                raise ValueError(f"Image path does not exist: {self.image_path}")
            if self.image_path.suffix.lower() not in _SUPPORTED_IMAGE_EXTENSIONS:
                raise ValueError(
                    f"Unsupported image format '{self.image_path.suffix}'. "
                    f"Supported: {sorted(_SUPPORTED_IMAGE_EXTENSIONS)}"
                )
        return self

    def to_voyage_content(self) -> list[str | Any]:
        """Return content in the format expected by voyageai.AsyncClient.multimodal_embed.

        The Voyage Python SDK expects a list of strings and PIL.Image.Image objects,
        not the dict/base64 format used by the REST API.
        """
        from PIL import Image

        content: list[str | Any] = []
        if self.text:
            content.append(self.text)
        if self.image_path:
            content.append(Image.open(self.image_path))
        return content


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

    async def embed_multimodal(
        self,
        inputs: list[MultimodalInput],
        input_type: Literal["document", "query"] = "document",
    ) -> list[list[float]]:
        if not inputs:
            return []

        all_embeddings: list[list[float]] = []
        for i in range(0, len(inputs), _MULTIMODAL_BATCH_SIZE):
            batch = inputs[i : i + _MULTIMODAL_BATCH_SIZE]
            voyage_inputs = [inp.to_voyage_content() for inp in batch]
            response = await self._client.multimodal_embed(
                voyage_inputs,
                model=_VOYAGE_MULTIMODAL_MODEL,
                input_type=input_type,
            )
            all_embeddings.extend(response.embeddings)

        record_tool_call(
            "voyage.embed_multimodal",
            f"inputs={len(inputs)}, type={input_type}",
            f"vectors={len(all_embeddings)}, dim={len(all_embeddings[0]) if all_embeddings else 0}",
        )
        return all_embeddings


@lru_cache(maxsize=1)
def get_embedding_client() -> EmbeddingClient:
    from agent_runtime.config import get_config
    return EmbeddingClient(api_key=get_config().voyage_api_key)
