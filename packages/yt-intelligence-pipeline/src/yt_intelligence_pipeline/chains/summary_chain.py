from __future__ import annotations

from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel

from yt_intelligence_pipeline.models import VideoMetadata
from yt_intelligence_pipeline.utils.retry import with_retries


class SummaryResult(BaseModel):
    summary: str
    key_takeaways: list[str]
    tags: list[str]


SUMMARY_SYSTEM_PROMPT = """\
You are a technical knowledge curator. Given a cleaned transcript and video metadata, \
produce a structured analysis. Your output must include:

summary: A concise TL;DR paragraph (3-5 sentences) capturing what the viewer will learn \
and why it matters. Written in third person, present tense.

key_takeaways: A list of 5-10 concrete, actionable bullet points. Each should be a \
complete thought that stands on its own — specific enough to be useful without rewatching.

tags: A list of 5-15 Obsidian-style tags (lowercase, hyphenated, no # prefix). \
Include: the main technology/framework, subtopics covered, content type \
(tutorial, walkthrough, deep-dive, etc.), and relevant skill level if apparent.

Focus on technical accuracy. Use the video title and channel to improve tag relevance.
"""

_chain = None


def _get_chain(api_key: str):  # type: ignore[return]
    global _chain
    if _chain is None:
        llm = ChatAnthropic(model="claude-sonnet-4-6", temperature=0, api_key=api_key)
        structured_llm = llm.with_structured_output(SummaryResult)
        prompt = ChatPromptTemplate.from_messages([
            ("system", SUMMARY_SYSTEM_PROMPT),
            ("human", (
                "Video title: {title}\n"
                "Channel: {channel}\n\n"
                "Transcript:\n{transcript}"
            )),
        ])
        _chain = prompt | structured_llm
    return _chain


@with_retries
def run_summary_chain(
    cleaned_transcript: str, video_metadata: VideoMetadata, api_key: str
) -> SummaryResult:
    return _get_chain(api_key).invoke({
        "title": video_metadata.title,
        "channel": video_metadata.channel,
        "transcript": cleaned_transcript,
    })
