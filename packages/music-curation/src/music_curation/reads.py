"""Text renderings of what the agent returns, shared by the CLI and the chat.

Each returns the exact text the CLI prints for that command (joined lines, no trailing newline).
"""
from __future__ import annotations

from music_curation.models import Generation, MusicResult
from music_curation.retrieval import RetrievedContext


def render_result(result: MusicResult) -> str:
    lines: list[str] = []
    q = result.pending_question
    if q and q.get("ask"):
        lines += [
            "\n── Clarifying question ──────────────────────────────",
            f"Q: {q['question']}",
            f"   Suggestion: {q['suggestion']}",
            f"   Why: {q['reasoning']}",
            "",
        ]
    lines += [
        f"Status:    {result.status}",
        f"Run ID:    {result.run_id}",
        f"Cost:      ${result.cost_usd:.4f}",
        f"Wall time: {result.wall_time_sec:.1f}s",
    ]
    for i, prompt in enumerate(result.prompts, 1):
        lines.append(f"\n── Prompt {i} ─────────────────────────────────────────")
        if i <= len(result.suggested_titles):
            lines.append(f"Title: {result.suggested_titles[i-1]}")
        lines.append(f"Style ({len(prompt.style_field)} chars):\n{prompt.style_field}")
        if prompt.lyrics_field:
            lines.append(f"\nLyrics:\n{prompt.lyrics_field}")
        if i <= len(result.generation_ids):
            lines.append(f"\nGeneration ID: {result.generation_ids[i-1]}")
            lines.append("(Use 'music-curation report <id> --reaction <X>' after running in Suno)")
    if result.theory_reasoning:
        lines.append("\n── Theory Reasoning ─────────────────────────────────")
        lines.append(result.theory_reasoning)
    if result.cross_references:
        lines.append(f"\n── Similar Prior Generations ({len(result.cross_references)}) ──────────")
        for ref in result.cross_references:
            lines.append(f"  [{ref.reaction}] {ref.suggested_track_title or ref.entry_id[:8]}")
            lines.append(f"    {ref.style_field_excerpt}...")
    if result.report_path:
        lines.append(f"\nReport: {result.report_path}")
    return "\n".join(lines)


def render_pending(pending: list[Generation]) -> str:
    if not pending:
        return "No pending generations."
    lines = [f"{len(pending)} pending generation(s):\n"]
    for gen in pending:
        title = gen.suggested_track_title or gen.entry_id[:12]
        lines += [
            f"  {gen.entry_id}",
            f"  Title: {title}",
            f"  Style: {gen.style_field[:80]}...",
            f"  Created: {gen.created_at}",
            "  Use: music-curation report <id> --reaction <X>",
            "",
        ]
    return "\n".join(lines)


def render_recall(ctx: RetrievedContext) -> str:
    if ctx.is_empty():
        return "No results found."
    lines: list[str] = []
    if ctx.prior_generations:
        lines.append(f"\n── Prior Generations ({len(ctx.prior_generations)}) ────────────────")
        for score, gen in ctx.prior_generations:
            title = gen.suggested_track_title or gen.entry_id[:12]
            rating_str = f" ★{gen.rating}" if gen.rating is not None else ""
            lines.append(f"  [{score:.3f}] {title} (reaction={gen.reaction}{rating_str})")
            lines.append(f"    {gen.style_field[:100]}...")
    if ctx.taste_lessons:
        lines.append(f"\n── Taste Lessons ({len(ctx.taste_lessons)}) ─────────────────────")
        for score, lesson in ctx.taste_lessons:
            lines.append(f"  [{score:.3f}][{lesson.valence}/{lesson.scope}] {lesson.statement[:80]}")
    if ctx.suno_facts:
        lines.append(f"\n── Suno Facts ({len(ctx.suno_facts)}) ──────────────────────────")
        for score, statement, _ in ctx.suno_facts:
            lines.append(f"  [{score:.3f}] {statement[:80]}")
    if ctx.tutorial_hits:
        lines.append(f"\n── Tutorial Knowledge ({len(ctx.tutorial_hits)}) ─────────────────")
        for score, content in ctx.tutorial_hits:
            if content:
                lines.append(f"  [{score:.3f}] {content[:100]}")
    return "\n".join(lines)


def render_chain(chain_root_id: str, entries: list[Generation]) -> str:
    if not entries:
        return f"No chain found for root_id: {chain_root_id}"
    lines = [f"Chain ({len(entries)} entries):\n"]
    for gen in entries:
        indent = "  " * (1 if gen.parent_id else 0)
        title = gen.suggested_track_title or gen.entry_id[:12]
        lines.append(f"{indent}[{gen.reaction}] {title}")
        if gen.change_summary:
            lines.append(f"{indent}  Changes: {gen.change_summary[:80]}")
        lines += [f"{indent}  Style: {gen.style_field[:80]}...", f"{indent}  ID: {gen.entry_id}", ""]
    return "\n".join(lines)
