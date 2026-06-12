"""technique_research_outputs is registered as an orchestrator search_knowledge
domain and the sub-agent tools are exposed."""
from __future__ import annotations


def test_domain_registered() -> None:
    from orchestrator.retrieval import DOMAINS

    spec = DOMAINS.get("technique_research_outputs")
    assert spec is not None
    assert spec.collection == "technique_research_outputs"
    assert spec.co_query_user_knowledge is True


def test_subagent_tools_exposed() -> None:
    from orchestrator.tools import all_tools

    names = {t.name for t in all_tools()}
    assert {"technique_recall", "technique_identify"} <= names
