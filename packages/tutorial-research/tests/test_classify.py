from __future__ import annotations

import pytest

from tutorial_research.classify import classify_request


def test_url_implies_ingest():
    assert classify_request("https://www.youtube.com/watch?v=abc123") == "ingest"


def test_url_in_sentence_implies_ingest():
    assert classify_request("please ingest https://youtu.be/abc for me") == "ingest"


def test_find_phrase_implies_retrieve():
    assert classify_request("find me tutorials on asyncio") == "retrieve"


def test_search_existing_implies_retrieve():
    assert classify_request("search existing tutorials about decorators") == "retrieve"


def test_what_do_we_have_implies_retrieve():
    assert classify_request("what do we have on fastapi?") == "retrieve"


def test_show_me_what_implies_retrieve():
    assert classify_request("show me what we have about pydantic") == "retrieve"


def test_generic_topic_implies_research():
    assert classify_request("python async patterns") == "research"


def test_generic_question_implies_research():
    assert classify_request("how does asyncio work in python") == "research"


def test_explicit_research_overrides_url():
    assert classify_request("https://youtube.com/watch?v=x", explicit="research") == "research"


def test_explicit_retrieve_overrides_generic():
    assert classify_request("python asyncio", explicit="retrieve") == "retrieve"


def test_explicit_ingest_overrides_retrieve_phrase():
    assert classify_request("find tutorials on asyncio", explicit="ingest") == "ingest"
