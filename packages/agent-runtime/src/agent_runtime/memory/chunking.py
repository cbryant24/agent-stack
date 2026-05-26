from __future__ import annotations

import re
from dataclasses import dataclass, field

import tiktoken

_ENCODING = tiktoken.get_encoding("cl100k_base")

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass
class DocumentChunk:
    text: str
    chunk_index: int
    start_char: int
    end_char: int
    token_count: int
    heading_context: str = ""


def _tokenize(text: str) -> list[int]:
    return _ENCODING.encode(text)


def _decode(tokens: list[int]) -> str:
    return _ENCODING.decode(tokens)


def chunk_document(
    text: str,
    *,
    target_tokens: int = 512,
    overlap_tokens: int = 64,
) -> list[DocumentChunk]:
    if not text.strip():
        return []

    # Split on paragraph boundaries first
    paragraphs = [p for p in re.split(r"\n\n+", text) if p.strip()]

    chunks: list[DocumentChunk] = []
    prev_overlap_tokens: list[int] = []
    chunk_index = 0
    char_offset = 0

    # Track char positions by walking the original text
    para_positions: list[tuple[str, int]] = []
    pos = 0
    for para in re.split(r"(\n\n+)", text):
        if para.strip():
            para_positions.append((para, pos))
        pos += len(para)

    para_iter = iter(para_positions)

    def emit_chunk(token_buf: list[int], start: int, end: int) -> None:
        nonlocal chunk_index
        chunk_text = _decode(token_buf)
        chunks.append(DocumentChunk(
            text=chunk_text,
            chunk_index=chunk_index,
            start_char=start,
            end_char=end,
            token_count=len(token_buf),
        ))
        chunk_index += 1

    current_tokens: list[int] = list(prev_overlap_tokens)
    current_start = 0
    current_end = 0

    for para, para_start in para_positions:
        para_tokens = _tokenize(para)
        para_end = para_start + len(para)

        # If adding this paragraph would exceed target, flush first
        while len(current_tokens) + len(para_tokens) > target_tokens and current_tokens:
            # Try to split at sentence boundaries within what we have
            current_text = _decode(current_tokens)
            sentences = _SENTENCE_END.split(current_text)
            if len(sentences) > 1:
                # Keep all but the last sentence in the current chunk
                flush_text = " ".join(sentences[:-1])
                flush_tokens = _tokenize(flush_text)
                tail_text = sentences[-1]
                tail_tokens = _tokenize(tail_text)
                emit_chunk(flush_tokens, current_start, current_end)
                prev_overlap_tokens = flush_tokens[-overlap_tokens:] if overlap_tokens else []
                current_tokens = list(prev_overlap_tokens) + tail_tokens
                current_start = current_end - len(_decode(prev_overlap_tokens))
            else:
                # No sentence boundary; hard cut at target_tokens
                emit_chunk(current_tokens[:target_tokens], current_start, current_end)
                prev_overlap_tokens = current_tokens[target_tokens - overlap_tokens:target_tokens] if overlap_tokens else []
                current_tokens = list(prev_overlap_tokens) + current_tokens[target_tokens:]
                current_start = current_end - len(_decode(prev_overlap_tokens))
            break

        if not current_tokens:
            current_start = para_start

        current_tokens.extend(para_tokens)
        current_end = para_end

    if current_tokens:
        emit_chunk(current_tokens, current_start, current_end)

    return chunks


def chunk_document_with_structure(
    text: str,
    headings: list[tuple[int, str]],
    *,
    target_tokens: int = 512,
    overlap_tokens: int = 64,
) -> list[DocumentChunk]:
    base_chunks = chunk_document(text, target_tokens=target_tokens, overlap_tokens=overlap_tokens)

    # Sort headings by char position
    sorted_headings = sorted(headings, key=lambda h: h[0])

    def nearest_heading(char_pos: int) -> str:
        relevant = [h for h in sorted_headings if h[0] <= char_pos]
        return relevant[-1][1] if relevant else ""

    result: list[DocumentChunk] = []
    for chunk in base_chunks:
        heading = nearest_heading(chunk.start_char)
        prefixed_text = f"{heading}\n\n{chunk.text}" if heading else chunk.text
        result.append(DocumentChunk(
            text=prefixed_text,
            chunk_index=chunk.chunk_index,
            start_char=chunk.start_char,
            end_char=chunk.end_char,
            token_count=chunk.token_count + (len(_tokenize(heading)) + 2 if heading else 0),
            heading_context=heading,
        ))

    return result
