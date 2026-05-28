from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from tutorial_research.constants import MAX_SYNTHESIS_TOKENS
from tutorial_research.models import RetrievedChunk


def _chunk(source_id: str, content: str) -> RetrievedChunk:
    return RetrievedChunk(score=0.9, source_id=source_id, content=content)


def _mock_response(text: str, input_tokens: int = 100, output_tokens: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.content = [MagicMock(text=text)]
    resp.usage = MagicMock(input_tokens=input_tokens, output_tokens=output_tokens)
    return resp


class TestSynthesize:
    def test_uses_max_synthesis_tokens(self) -> None:
        """Verify the API call uses MAX_SYNTHESIS_TOKENS, not a lower hardcoded value."""
        from agent_runtime import BudgetEnvelope
        from agent_runtime.budget import BudgetTracker
        from tutorial_research.synthesis import synthesize

        chunks = [_chunk("youtube:aaa", "asyncio event loop internals")]
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=_mock_response("Summary text"))

        async def _run() -> None:
            async with BudgetTracker(BudgetEnvelope(), "test-agent") as tracker:
                await synthesize("python asyncio", chunks, tracker, mock_client)

        asyncio.run(_run())

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["max_tokens"] == MAX_SYNTHESIS_TOKENS
        assert MAX_SYNTHESIS_TOKENS == 8192

    def test_returns_empty_string_for_no_chunks(self) -> None:
        from agent_runtime import BudgetEnvelope
        from agent_runtime.budget import BudgetTracker
        from tutorial_research.synthesis import synthesize

        mock_client = AsyncMock()

        async def _run() -> str:
            async with BudgetTracker(BudgetEnvelope(), "test-agent") as tracker:
                return await synthesize("python asyncio", [], tracker, mock_client)

        result = asyncio.run(_run())
        assert result == ""
        mock_client.messages.create.assert_not_called()

    def test_returns_model_text(self) -> None:
        from agent_runtime import BudgetEnvelope
        from agent_runtime.budget import BudgetTracker
        from tutorial_research.synthesis import synthesize

        chunks = [_chunk("youtube:aaa", "content")]
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=_mock_response("Research synthesis output."))

        async def _run() -> str:
            async with BudgetTracker(BudgetEnvelope(), "test-agent") as tracker:
                return await synthesize("python asyncio", chunks, tracker, mock_client)

        result = asyncio.run(_run())
        assert result == "Research synthesis output."
