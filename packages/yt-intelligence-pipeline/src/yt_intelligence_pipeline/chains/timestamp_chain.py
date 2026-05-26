from __future__ import annotations

from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel

from yt_intelligence_pipeline.models import TimestampEntry
from yt_intelligence_pipeline.utils.retry import with_retries


class _TimestampData(BaseModel):
    timestamp_seconds: int
    label: str


class _TimestampResult(BaseModel):
    timestamps: list[_TimestampData]


TIMESTAMP_SYSTEM_PROMPT = """\
You are analyzing a timed transcript to identify the best moments for screenshots in a \
technical tutorial video. Each line of the transcript has the format [M:SS] text.

Select 5-10 timestamps that capture visually rich moments worth screenshotting. \
Prioritize in this order:
1. Configuration panels, settings screens, or dashboards being shown
2. Code editors or terminals with meaningful commands or output
3. Architecture or flow diagrams being explained
4. UI walkthroughs demonstrating a key feature
5. Before/after comparisons or final results

Avoid: talking-head moments, title cards, blank screens, or transitions.

For each timestamp:
- timestamp_seconds: the integer number of seconds from the start (convert MM:SS to seconds)
- label: a short description (10-15 words) of what is visible at that moment

Return only timestamps that are likely to be visually meaningful.
"""

_chain = None


def _get_chain():  # type: ignore[return]
    global _chain
    if _chain is None:
        llm = ChatAnthropic(model="claude-sonnet-4-6", temperature=0)
        structured_llm = llm.with_structured_output(_TimestampResult)
        prompt = ChatPromptTemplate.from_messages([
            ("system", TIMESTAMP_SYSTEM_PROMPT),
            ("human", "{timed_transcript}"),
        ])
        _chain = prompt | structured_llm
    return _chain


@with_retries
def run_timestamp_chain(timed_transcript: str) -> list[TimestampEntry]:
    result: _TimestampResult = _get_chain().invoke({"timed_transcript": timed_transcript})
    return [
        TimestampEntry(timestamp_seconds=t.timestamp_seconds, label=t.label)
        for t in result.timestamps
    ]
