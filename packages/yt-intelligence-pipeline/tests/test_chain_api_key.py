"""Regression test for the Anthropic auth bug: the transcript chains must forward
the configured API key into ChatAnthropic rather than relying on the (unset)
ANTHROPIC_API_KEY env fallback. This path had no test, which is how the bug shipped.

Each chain builds a lazy module-level `_chain` singleton in `_get_chain(api_key)`.
We patch ChatAnthropic to capture its kwargs and assert `api_key` is threaded through,
resetting the singleton around each test so the build actually runs.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from yt_intelligence_pipeline.chains import cleanup_chain, summary_chain, timestamp_chain

CHAIN_MODULES = [cleanup_chain, summary_chain, timestamp_chain]


@pytest.fixture(autouse=True)
def _reset_chain_singletons():
    """Force a fresh build in each test and avoid leaking a mock-built chain."""
    for mod in CHAIN_MODULES:
        mod._chain = None
    yield
    for mod in CHAIN_MODULES:
        mod._chain = None


@pytest.mark.parametrize("mod", CHAIN_MODULES, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_get_chain_forwards_api_key(mod) -> None:
    with patch.object(mod, "ChatAnthropic") as mock_cls:
        mod._get_chain("sk-ant-test-key")

    mock_cls.assert_called_once()
    assert mock_cls.call_args.kwargs.get("api_key") == "sk-ant-test-key"
