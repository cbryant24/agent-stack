from __future__ import annotations

from langchain_anthropic import ChatAnthropic
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from yt_intelligence_pipeline.utils.retry import with_retries

CLEANUP_SYSTEM_PROMPT = """\
You are a transcript editor specializing in technical software content. \
Clean up the raw transcript provided by the user. Follow these rules exactly:

- Preserve all technical terms, library names, CLI commands, and code snippets verbatim
- Remove filler words and phrases: uh, um, like, you know, sort of, kind of, right, \
  okay so, alright, basically, literally, actually (when used as filler)
- Add proper punctuation and capitalization
- Break into logical paragraphs — start a new paragraph when the topic meaningfully shifts
- Do not summarize, condense, or omit any substantive content
- Do not add information not present in the original transcript
- Output only the cleaned transcript with no preamble, commentary, or section headers
"""

_chain = None


def _get_chain(api_key: str):  # type: ignore[return]
    global _chain
    if _chain is None:
        llm = ChatAnthropic(model="claude-sonnet-4-6", temperature=0, api_key=api_key)
        prompt = ChatPromptTemplate.from_messages([
            ("system", CLEANUP_SYSTEM_PROMPT),
            ("human", "{transcript}"),
        ])
        _chain = prompt | llm | StrOutputParser()
    return _chain


@with_retries
def run_cleanup_chain(raw_transcript: str, api_key: str) -> str:
    return _get_chain(api_key).invoke({"transcript": raw_transcript})
