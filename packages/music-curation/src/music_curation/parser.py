"""Seed file parser for Suno session-summary markdown files.

Extracts four categories from each file:
  - ParsedPrompt      → Generation entries in music_curation_memory
  - ParsedSunoFact    → user_knowledge entries (via UserKnowledgeStore.bulk_load_verified)
  - ParsedTasteLesson → TasteLesson candidates (require user confirmation)
  - ParsedTemplate    → Template entries (explicit: auto-write; heuristic: yes/no confirm)

Files are structured markdown, not prose — the parser uses section headers and
code-block detection rather than LLM extraction. The README and session files
are handled with separate entry points.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

from music_curation.constants import (
    REACTION_LIKED,
    REACTION_DISLIKED,
    REACTION_LIKED_WITH_CHANGES,
    REACTION_LOST_TRACK,
    REACTION_LOVED,
)
from music_curation.models import (
    ParsedPrompt,
    ParsedSession,
    ParsedSunoFact,
    ParsedTasteLesson,
    ParsedTemplate,
)

# ── Reaction detection ────────────────────────────────────────────────────────

_LOVED_PATTERNS = [
    re.compile(r"USER LOVED THIS", re.IGNORECASE),
    re.compile(r"✅.*loved", re.IGNORECASE),
]
_APPROVED_PATTERNS = [
    re.compile(r"\*\*Status:\*\*\s*✅\s*User (liked|approved)", re.IGNORECASE),
    re.compile(r"✅\s*(Recommended|Best|User liked|User approved)", re.IGNORECASE),
    re.compile(r"\(Recommended\)", re.IGNORECASE),
    re.compile(r"BEST of", re.IGNORECASE),
    re.compile(r"worked well", re.IGNORECASE),
    re.compile(r"\*\*Status:\*\*\s*✅\s*User\b", re.IGNORECASE),
    # "liked" without "but" qualifier — check after liked_with_changes patterns
    re.compile(r"—\s*liked\s*\)", re.IGNORECASE),  # "(Variation N — liked)"
    re.compile(r"✅.*\bliked\b(?!\s+but)", re.IGNORECASE),
]
_LIKED_CHANGES_PATTERNS = [
    re.compile(r"⚠️", re.UNICODE),
    re.compile(r"liked but wanted", re.IGNORECASE),
    re.compile(r"liked the .+, not the", re.IGNORECASE),
    re.compile(r"liked but too", re.IGNORECASE),
    re.compile(r"getting closer", re.IGNORECASE),
]
_DISLIKED_PATTERNS = [
    re.compile(r"\*\*Status:\*\*\s*❌", re.IGNORECASE),
    re.compile(r"❌", re.UNICODE),
    re.compile(r"didn't (work|like)", re.IGNORECASE),
    re.compile(r"Didn't Work", re.IGNORECASE),
    re.compile(r"failed:", re.IGNORECASE),
    re.compile(r"didn't work well", re.IGNORECASE),
]

_STATUS_FIELD_RE = re.compile(r"\*\*Status:\*\*\s*(.+)", re.IGNORECASE)


def _infer_reaction(text: str, section_framing: str = "") -> str:
    """Infer reaction from header text + immediately-following content."""
    combined = (text + " " + section_framing).strip()

    for pat in _LOVED_PATTERNS:
        if pat.search(combined):
            return REACTION_LOVED

    for pat in _DISLIKED_PATTERNS:
        if pat.search(combined):
            return REACTION_DISLIKED

    for pat in _LIKED_CHANGES_PATTERNS:
        if pat.search(combined):
            return REACTION_LIKED_WITH_CHANGES

    for pat in _APPROVED_PATTERNS:
        if pat.search(combined):
            return REACTION_LIKED

    return REACTION_LOST_TRACK


# ── BPM / language extraction ─────────────────────────────────────────────────

_BPM_RE = re.compile(r"(\d+)(?:\s*[-–]\s*\d+)?\s*BPM", re.IGNORECASE)
_LANG_PATTERNS = [
    (re.compile(r"french (?:female )?vocals?|parisian|french lyrics", re.IGNORECASE), "French"),
    (re.compile(r"japanese (?:female )?vocals?|tokyo|japanese lyrics", re.IGNORECASE), "Japanese"),
    (re.compile(r"english (?:female )?vocals?", re.IGNORECASE), "English"),
    (re.compile(r"multilingual", re.IGNORECASE), "Multilingual"),
]


def _extract_bpm(style_field: str) -> int | None:
    m = _BPM_RE.search(style_field)
    if not m:
        return None
    val_str = m.group(1)
    full_match = m.group(0)
    range_m = re.search(r"(\d+)\s*[-–]\s*(\d+)", full_match)
    if range_m:
        lo, hi = int(range_m.group(1)), int(range_m.group(2))
        return (lo + hi) // 2
    return int(val_str)


def _extract_language(style_field: str) -> str | None:
    for pat, lang in _LANG_PATTERNS:
        if pat.search(style_field):
            return lang
    return None


# ── Markdown structural helpers ───────────────────────────────────────────────

def _extract_code_blocks(text: str) -> list[str]:
    """Return all fenced code block contents in order."""
    return re.findall(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)


def _strip_reaction_markers(text: str) -> str:
    """Remove ✅/❌/⚠️ and Status-field prefixes from header text."""
    text = re.sub(r"[✅❌⚠️⭐]", "", text)
    text = re.sub(r"\*\*Status:\*\*\s*\S+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\(Recommended\)", "", text, flags=re.IGNORECASE)
    return text.strip(" -–—:")


class _Section(NamedTuple):
    level: int        # 1 = H2, 2 = H3
    heading: str
    content: str


def _split_sections(text: str, level: int = 2) -> list[_Section]:
    """Split markdown into sections at the given heading level."""
    hashes = "#" * level
    pattern = re.compile(rf"^{hashes} (.+)$", re.MULTILINE)
    matches = list(pattern.finditer(text))
    sections: list[_Section] = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append(_Section(level, m.group(1).strip(), text[start:end].strip()))
    return sections


# ── Section classification ────────────────────────────────────────────────────

_LEARNING_HEADING_RE = re.compile(
    r"key (?:learnings?|notes?)|suno (?:behavior|specific)|learnings?|what works?|"
    r"what didn't work|best practices?|quick tips?|lessons?|observations?|"
    r"essential structure|vocal control|production style|prompt construction",
    re.IGNORECASE,
)
_TEMPLATE_HEADING_RE = re.compile(
    r"template|pattern|quick reference|prompt structure|style variation|"
    r"base concept|recap|prompts? created|final (?:recommendations?|prompts?)|"
    r"earlier prompts?",
    re.IGNORECASE,
)
# Headings that are sub-fields of a prompt, not prompt containers themselves.
_SUBFIELD_HEADING_RE = re.compile(
    r"^(?:style of music|lyrics?|style:|lyrics? field|notes?|translations?)[\s:]*$",
    re.IGNORECASE,
)


def _is_subfield_heading(heading: str) -> bool:
    return bool(_SUBFIELD_HEADING_RE.match(heading.strip()))


def _section_has_prompts(content: str) -> bool:
    blocks = _extract_code_blocks(content)
    return bool(blocks) and any(len(b) > 30 for b in blocks)


def _is_learning_section(heading: str) -> bool:
    return bool(_LEARNING_HEADING_RE.search(heading))


def _is_template_section(heading: str) -> bool:
    return bool(_TEMPLATE_HEADING_RE.search(heading))


# ── Suno-fact extraction from bullet lists ────────────────────────────────────

_SUNO_FACT_TRIGGERS = re.compile(
    r"suno (tends?|will|adds?|generates?|uses?|requires?|treats?|interprets?|"
    r"defaults?|needs?|reads?|produces?)|"
    r"(?:must|should|never|always|avoid|require|use)\s.{0,30}suno|"
    r"character limit|tag syntax|\[bracket\]|parenthes|style field|lyrics field|"
    r"tempo range|bpm is|explicit negation|unaccompanied|isolated",
    re.IGNORECASE,
)
_TASTE_TRIGGERS = re.compile(
    r"user (?:loved|liked|disliked|hated|preferred|didn't like)|"
    r"what (?:user )?loved|what (?:user )?didn't work|"
    r"success formula|✅ what|❌ what|"
    r"worked well for|didn't work for",
    re.IGNORECASE,
)


def _classify_bullet(bullet: str) -> str:
    """Returns 'suno_fact', 'taste', or 'skip'."""
    if _SUNO_FACT_TRIGGERS.search(bullet):
        return "suno_fact"
    if _TASTE_TRIGGERS.search(bullet):
        return "taste"
    # Neutral production knowledge with Suno-specific signals goes to suno_fact
    if re.search(r"keyword|descriptor|phrasing|`\[.+\]`|\[Instrumental\]", bullet):
        return "suno_fact"
    return "skip"


def _extract_bullets(text: str) -> list[str]:
    """Extract non-empty bullet-list items (- or * or numbered)."""
    bullets = []
    for line in text.splitlines():
        stripped = line.strip()
        m = re.match(r"^[-*•]\s+(.+)$", stripped) or re.match(r"^\d+\.\s+(.+)$", stripped)
        if m:
            bullets.append(m.group(1).strip())
    return bullets


def _parse_learning_section(
    content: str,
    session_id: str,
    heading: str,
) -> tuple[list[ParsedSunoFact], list[ParsedTasteLesson]]:
    """Extract suno_facts and taste lessons from a learnings section."""
    suno_facts: list[ParsedSunoFact] = []
    taste_lessons: list[ParsedTasteLesson] = []

    # For structured "What Worked / What Didn't" subsections, track valence.
    lines = content.splitlines()
    current_valence: str | None = None
    # When True, all bullets are taste regardless of _classify_bullet result.
    in_explicit_taste_block: bool = False

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Detect subsection valence from MD headings (## / ### / ####)
        if re.match(r"^#{2,4}\s+", line):
            sub_heading = re.sub(r"^#{2,4}\s+", "", line).lower()
            if any(w in sub_heading for w in ["what worked", "loved", "✅", "success"]):
                current_valence = "positive"
                in_explicit_taste_block = True
            elif any(w in sub_heading for w in ["what didn't", "didn't work", "❌", "avoid"]):
                current_valence = "negative"
                in_explicit_taste_block = True
            else:
                current_valence = None
                in_explicit_taste_block = False
            i += 1
            continue

        # Also detect bold-label valence markers like **✅ What User Loved:**
        # These appear in files that don't use heading syntax for subsections.
        bold_label_m = re.match(r"^\*\*[✅❌🎯⭐]?\s*(.+?)\*\*:?\s*$", line)
        if bold_label_m:
            label_text = bold_label_m.group(1).lower()
            if any(w in label_text for w in ["what user loved", "what worked", "user loved", "success formula"]):
                current_valence = "positive"
                in_explicit_taste_block = True
            elif any(w in label_text for w in ["what didn't", "didn't work", "user didn't", "avoid", "what not"]):
                current_valence = "negative"
                in_explicit_taste_block = True
            # Don't reset valence on unrecognised bold labels — preserve context
            i += 1
            continue

        # Process bullet items
        m = re.match(r"^[-*•]\s+(.+)$", line) or re.match(r"^\d+\.\s+(.+)$", line)
        if m:
            bullet = m.group(1).strip()
            # Strip bold markers and inline code for cleaner text
            clean = re.sub(r"\*\*(.+?)\*\*", r"\1", bullet)
            clean = re.sub(r"`(.+?)`", r"\1", clean)

            # When inside an explicit taste block (bold-label or heading), capture
            # ALL bullets as taste — don't rely on _classify_bullet matching.
            if in_explicit_taste_block and current_valence and len(clean) > 5:
                scope = _infer_taste_scope(clean)
                taste_lessons.append(ParsedTasteLesson(
                    statement=clean,
                    valence=current_valence,
                    scope=scope,
                    session_id=session_id,
                    is_explicit=False,
                ))
                i += 1
                continue

            classification = _classify_bullet(clean)

            if classification == "suno_fact":
                tags: list[str] = []
                if re.search(r"lyric|vocal|voice", clean, re.IGNORECASE):
                    tags.append("vocal_control")
                if re.search(r"bpm|tempo|speed", clean, re.IGNORECASE):
                    tags.append("tempo")
                if re.search(r"limit|character|length", clean, re.IGNORECASE):
                    tags.append("style_field")
                if re.search(r"\[.+?\]|tag|bracket|marker", clean, re.IGNORECASE):
                    tags.append("structure_tags")
                suno_facts.append(ParsedSunoFact(statement=clean, topic_tags=tags))

            elif classification == "taste":
                valence: str
                if current_valence:
                    valence = current_valence
                elif re.search(
                    r"loved|liked|worked|preferred|effective|best|great|winner",
                    clean, re.IGNORECASE,
                ):
                    valence = "positive"
                elif re.search(
                    r"didn't|disliked|failed|avoided|worse|not.*work|polished|too",
                    clean, re.IGNORECASE,
                ):
                    valence = "negative"
                else:
                    valence = "positive"

                taste_lessons.append(ParsedTasteLesson(
                    statement=clean,
                    valence=valence,
                    scope=_infer_taste_scope(clean),
                    session_id=session_id,
                    is_explicit=False,
                ))

        i += 1

    return suno_facts, taste_lessons


def _infer_taste_scope(text: str) -> str:
    if re.search(r"\bvocal|voice|singer|lyric|breathy|smoky\b", text, re.IGNORECASE):
        return "vocal"
    if re.search(r"\bbass|drum|percussion|instrument|guitar|piano|synth|cowbell|808\b", text, re.IGNORECASE):
        return "instrumentation"
    if re.search(r"\bproduction|mix|sound|texture|aesthetic|polished|raw|distort|reverb\b", text, re.IGNORECASE):
        return "production"
    if re.search(r"\bgenre|style|type|phonk|lo.?fi|trap|jazz|hip.?hop|orchestral\b", text, re.IGNORECASE):
        return "genre"
    return "general"


# ── Prompt extraction from a heading + its content ───────────────────────────

def _build_prompt(
    heading: str,
    style_field: str,
    lyrics_field: str | None,
    full_content: str,
    session_id: str,
    section_framing: str = "",
    parent_index: int | None = None,
) -> ParsedPrompt:
    """Build a ParsedPrompt from already-extracted fields."""
    content_preview = " ".join(
        ln.strip() for ln in full_content.splitlines()[:8] if ln.strip()
    )
    reaction = _infer_reaction(heading + " " + content_preview, section_framing)

    raw_name = _strip_reaction_markers(heading)
    raw_name = re.sub(r"^\d+\.\s*", "", raw_name).strip()

    # Extract change summary from "Key Changes from Version N" blocks
    change_summary: str | None = None
    change_match = re.search(
        r"Key [Cc]hanges?\s+from\s+(?:Version\s+)?\d+[:\n](.*?)(?:\n\n|\Z)",
        full_content, re.DOTALL,
    )
    if change_match:
        change_text = change_match.group(1).strip()
        change_summary = re.sub(r"\n[-*]\s+", "; ", change_text).strip()

    if not change_summary:
        improvements_match = re.search(
            r"Key improvements[:\n](.*?)(?:\n\n|\Z)", full_content, re.DOTALL
        )
        if improvements_match:
            impr_text = improvements_match.group(1).strip()
            bullets = [
                re.sub(r"^[-✅*]\s*", "", ln).strip()
                for ln in impr_text.splitlines() if ln.strip()
            ]
            change_summary = "; ".join(b for b in bullets if b)

    return ParsedPrompt(
        session_id=session_id,
        name=raw_name or heading[:60],
        style_field=style_field,
        lyrics_field=lyrics_field,
        reaction=reaction,
        bpm=_extract_bpm(style_field),
        language=_extract_language(style_field),
        suggested_track_title=raw_name[:50] if raw_name else None,
        change_summary=change_summary,
        parent_index=parent_index,
        is_explicit_template=False,
    )


def _extract_style_and_lyrics(content: str) -> tuple[str, str | None]:
    """Extract style_field and optional lyrics_field from section content.

    Handles two layouts:
    1. Flat: one or two bare code blocks (style first, then lyrics if present)
    2. Sub-field: H3/H4 sub-sections headed "Style of Music" / "Lyrics"
    """
    # Check for sub-field sub-sections first
    style_field = ""
    lyrics_field = None

    sub_sections = _split_sections(content, level=3) + _split_sections(content, level=4)
    style_subs = [s for s in sub_sections if re.search(r"^style", s.heading, re.IGNORECASE)]
    lyrics_subs = [s for s in sub_sections if re.search(r"^lyrics?", s.heading, re.IGNORECASE)]

    if style_subs:
        blocks = _extract_code_blocks(style_subs[0].content)
        if blocks:
            style_field = blocks[0].strip()
    if lyrics_subs:
        blocks = _extract_code_blocks(lyrics_subs[0].content)
        if blocks:
            lyrics_field = blocks[0].strip()

    if style_field:
        return style_field, lyrics_field

    # Flat layout: scan lines in order, pair adjacent code blocks as style then lyrics.
    # We also check labels like "**Style of Music:**" or "**Lyrics:**" that appear
    # immediately before a code block.
    lines = content.splitlines()
    i = 0
    pending_label: str = ""
    found_style = False

    while i < len(lines):
        line = lines[i].strip()

        # Detect label lines
        label_m = re.match(r"\*\*(.+?)\*\*:?$", line)
        if label_m:
            pending_label = label_m.group(1).lower()
            i += 1
            continue

        if line.startswith("```"):
            end = i + 1
            while end < len(lines) and not lines[end].strip().startswith("```"):
                end += 1
            block_text = "\n".join(lines[i + 1:end]).strip()

            is_lyrics = "lyrics" in pending_label or (
                found_style and not lyrics_field and _looks_like_lyrics(block_text)
            )

            if not found_style and not is_lyrics:
                style_field = block_text
                found_style = True
            elif found_style and not lyrics_field:
                lyrics_field = block_text

            pending_label = ""
            i = end + 1
            continue

        pending_label = ""
        i += 1

    return style_field, lyrics_field


def _looks_like_lyrics(text: str) -> bool:
    """True if a code block looks like lyrics (structural tags like [Hook], [Verse])."""
    return bool(re.search(r"\[(?:Hook|Verse|Chorus|Intro|Bridge|Outro|Instrumental)", text))


def _is_valid_suno_style(text: str) -> bool:
    """True if text looks like a real Suno style field (not a meta-template pattern).

    Rejects:
    - Template patterns where >30% of text is [Variable] slots
    - Blocks with fewer than 2 commas and no BPM (not comma-separated descriptors)
    - Workflow/evolution descriptions (contain "→" but no commas/BPM)
    """
    if not text or len(text) < 15:
        return False

    # Reject pure workflow descriptions
    if "→" in text and "," not in text:
        return False

    # Reject blocks dominated by [Variable] slots (template patterns)
    variable_chars = sum(len(m.group(0)) for m in _SWAP_VAR_RE.finditer(text))
    if variable_chars / len(text) > 0.30:
        return False

    # Must have at least 2 commas OR a BPM indicator
    has_commas = text.count(",") >= 2
    has_bpm = bool(_BPM_RE.search(text))
    if not has_commas and not has_bpm:
        return False

    return True


def _extract_prompt_from_section(
    heading: str,
    content: str,
    session_id: str,
    section_framing: str = "",
    parent_index: int | None = None,
) -> ParsedPrompt | None:
    """Extract a ParsedPrompt from a section with the given heading and content.

    Handles:
    - Flat code blocks (style first, optional lyrics second)
    - Sub-field headings (### Style of Music / ### Lyrics within the content)
    - Inline **Style of Music:** / **Lyrics:** labels before code blocks
    """
    style_field, lyrics_field = _extract_style_and_lyrics(content)

    if not style_field or not _is_valid_suno_style(style_field):
        return None

    return _build_prompt(
        heading, style_field, lyrics_field, content, session_id,
        section_framing=section_framing,
        parent_index=parent_index,
    )


# ── Parent-index inference ────────────────────────────────────────────────────

def _infer_parent_index(
    heading: str,
    content: str,
    prompt_index: int,
    all_headings: list[str],
) -> int | None:
    """Return the 0-based index of this prompt's parent, or None if root."""
    # Explicit "Key Changes from Version N" — index is N-1 (1-based to 0-based)
    m = re.search(r"[Kk]ey [Cc]hanges?\s+from\s+[Vv]ersion\s+(\d+)", content)
    if m:
        version_num = int(m.group(1))
        # Clamp to valid range: must refer to an earlier prompt
        idx = version_num - 1
        if 0 <= idx < prompt_index:
            return idx

    # Explicit "Same Style as Version N" or "Same Style as #N"
    # This means same style as prompt N (1-based within this session file).
    m = re.search(r"[Ss]ame [Ss]tyle as (?:Version\s+)?#?(\d+)", content)
    if m:
        ref_num = int(m.group(1))
        idx = ref_num - 1
        if 0 <= idx < prompt_index:
            return idx

    # Numbered iteration pattern: ALL headings start with a number.
    # "Iteration 1", "Iteration 2" or "1. Name", "2. Name"
    iteration_nums = [
        re.match(r"^(?:Iteration\s+)?(\d+)[\.\s-]", h.strip())
        for h in all_headings
    ]
    if all(iteration_nums) and prompt_index > 0:
        return prompt_index - 1

    return None


# ── Template detection ────────────────────────────────────────────────────────

_SWAP_VAR_RE = re.compile(r"\[([A-Z][A-Za-z_ ]+)\]")


def _extract_swap_variables(text: str) -> list[str]:
    return list({m.group(1) for m in _SWAP_VAR_RE.finditer(text)})


def _looks_like_template(style_text: str) -> bool:
    """True if the style text contains [Variable] swap slots."""
    return bool(_SWAP_VAR_RE.search(style_text))


# ── Session file parser ───────────────────────────────────────────────────────

def _collect_prompts_from_section(
    heading: str,
    content: str,
    session_id: str,
    section_framing: str,
    prompt_list: list[ParsedPrompt],
    template_list: list[ParsedTemplate],
) -> None:
    """Recursively collect prompts from a section.

    Handles three structural patterns:
    1. This section itself is the prompt unit (flat code blocks, or H3/H4 sub-fields
       named "Style of Music" / "Lyrics")
    2. Child H3 sections are individual prompts (most files)
    3. Child H3 sections are categories and H4 sections are individual prompts (file 7)
    """
    h3_sections = _split_sections(content, level=3)

    # Pattern 1 check: does content use sub-fields (Style of Music / Lyrics H3/H4)?
    subfield_h3s = [s for s in h3_sections if _is_subfield_heading(s.heading)]
    non_subfield_h3s = [s for s in h3_sections if not _is_subfield_heading(s.heading)]

    if subfield_h3s and not non_subfield_h3s:
        # The current section IS the prompt — sub-fields are style/lyrics fields
        parsed = _extract_prompt_from_section(
            heading, content, session_id, section_framing=section_framing,
            parent_index=None,
        )
        if parsed:
            if parsed.reaction == REACTION_LOST_TRACK and section_framing == "liked":
                parsed = parsed.model_copy(update={"reaction": REACTION_LIKED})
            prompt_list.append(parsed)
            _maybe_add_template(parsed, session_id, template_list)
        return

    if not non_subfield_h3s:
        # No H3 prompt sections: this section itself is the prompt (flat layout)
        if _section_has_prompts(content):
            prompt_index = len(prompt_list)
            parsed = _extract_prompt_from_section(
                heading, content, session_id, section_framing=section_framing,
                parent_index=None,
            )
            if parsed:
                if parsed.reaction == REACTION_LOST_TRACK and section_framing == "liked":
                    parsed = parsed.model_copy(update={"reaction": REACTION_LIKED})
                prompt_list.append(parsed)
                _maybe_add_template(parsed, session_id, template_list)
        return

    # Pattern 2 or 3: non-subfield H3 sections.
    # Check if H3 sections themselves contain H4 sections with code blocks
    # (pattern 3: H3 = category, H4 = individual prompt).
    first_non_subfield = non_subfield_h3s[0]
    h4_in_first = _split_sections(first_non_subfield.content, level=4)
    has_prompt_h4 = any(_section_has_prompts(s.content) for s in h4_in_first)

    if has_prompt_h4:
        # Pattern 3: go to H4 level
        for h3 in non_subfield_h3s:
            if _is_learning_section(h3.heading):
                continue  # handled elsewhere
            h4_sections = _split_sections(h3.content, level=4)
            h4_headings = [s.heading for s in h4_sections if _section_has_prompts(s.content)]
            h4_prompt_index = 0
            for h4 in h4_sections:
                if _is_learning_section(h4.heading):
                    continue
                if not _section_has_prompts(h4.content):
                    continue
                parent_idx = _infer_parent_index(
                    h4.heading, h4.content, h4_prompt_index, h4_headings
                )
                parsed = _extract_prompt_from_section(
                    h4.heading, h4.content, session_id,
                    section_framing=section_framing,
                    parent_index=parent_idx,
                )
                if parsed:
                    if parsed.reaction == REACTION_LOST_TRACK and section_framing == "liked":
                        parsed = parsed.model_copy(update={"reaction": REACTION_LIKED})
                    prompt_list.append(parsed)
                    h4_prompt_index += 1
                    _maybe_add_template(parsed, session_id, template_list)
        return

    # Pattern 2: H3 = individual prompts
    h3_headings = [s.heading for s in non_subfield_h3s if _section_has_prompts(s.content)]
    prompt_index = 0

    for h3 in non_subfield_h3s:
        if _is_learning_section(h3.heading):
            continue
        if not _section_has_prompts(h3.content):
            # Recurse: H3 with no direct code blocks but might have H4 prompts
            _collect_prompts_from_section(
                h3.heading, h3.content, session_id, section_framing,
                prompt_list, template_list,
            )
            continue

        parent_idx = _infer_parent_index(
            h3.heading, h3.content, prompt_index, h3_headings
        )
        parsed = _extract_prompt_from_section(
            h3.heading, h3.content, session_id,
            section_framing=section_framing,
            parent_index=parent_idx,
        )
        if parsed:
            if parsed.reaction == REACTION_LOST_TRACK and section_framing == "liked":
                parsed = parsed.model_copy(update={"reaction": REACTION_LIKED})
            prompt_list.append(parsed)
            prompt_index += 1
            _maybe_add_template(parsed, session_id, template_list)


def _maybe_add_template(
    parsed: ParsedPrompt,
    session_id: str,
    template_list: list[ParsedTemplate],
) -> None:
    """If the prompt has [Variable] swap slots, add a corresponding template entry."""
    if _looks_like_template(parsed.style_field):
        swap_vars = _extract_swap_variables(parsed.style_field)
        descriptor = _derive_template_descriptor(parsed.style_field, parsed.name)
        template_list.append(ParsedTemplate(
            name=parsed.name,
            descriptor=descriptor,
            style_pattern=parsed.style_field,
            swap_variables=swap_vars,
            source_session_id=session_id,
            is_explicit=False,
        ))


def parse_session_file(path: Path) -> ParsedSession:
    """Parse a Suno session-summary markdown file into structured ParsedSession."""
    text = path.read_text(encoding="utf-8")
    session_id = path.stem

    session = ParsedSession(session_id=session_id, source_path=str(path))
    source_text = text  # preserved for post-processing passes

    h2_sections = _split_sections(text, level=2)

    for h2 in h2_sections:
        # Learning sections — extract suno_facts and taste_lessons
        if _is_learning_section(h2.heading):
            facts, tastes = _parse_learning_section(h2.content, session_id, h2.heading)
            session.suno_facts.extend(facts)
            session.taste_lessons.extend(tastes)
            # Also recurse into H3 subsections in learning sections
            for h3 in _split_sections(h2.content, level=3):
                if _is_learning_section(h3.heading):
                    f, t = _parse_learning_section(h3.content, session_id, h3.heading)
                    session.suno_facts.extend(f)
                    session.taste_lessons.extend(t)
            continue

        # Template-only sections (prompt structure patterns without actual prompts)
        if _is_template_section(h2.heading) and not _section_has_prompts(h2.content):
            for block in _extract_code_blocks(h2.content):
                if len(block) > 20:
                    session.templates.append(ParsedTemplate(
                        name=h2.heading.strip(),
                        descriptor=_derive_template_descriptor(block, h2.heading),
                        style_pattern=block,
                        swap_variables=_extract_swap_variables(block),
                        source_session_id=session_id,
                        is_explicit=False,
                    ))
            continue

        # Determine section-level reaction framing
        framing = ""
        if re.search(
            r"final approved|best|recommended|prompts created|final prompts?",
            h2.heading, re.IGNORECASE,
        ):
            framing = "liked"
        elif re.search(r"earlier|reference|exploration|initial", h2.heading, re.IGNORECASE):
            framing = "earlier"

        # Collect prompts recursively (handles H3, H4, and sub-field patterns)
        _collect_prompts_from_section(
            h2.heading, h2.content, session_id, framing,
            session.prompts, session.templates,
        )

        # Always scan H3 subsections for learnings too (some files mix prompts + notes)
        for h3 in _split_sections(h2.content, level=3):
            if _is_learning_section(h3.heading):
                f, t = _parse_learning_section(h3.content, session_id, h3.heading)
                session.suno_facts.extend(f)
                session.taste_lessons.extend(t)

    session = _apply_session_post_processing(session, source_text)
    return _deduplicate_session(session)


# ── README parser ─────────────────────────────────────────────────────────────

def parse_readme(path: Path) -> ParsedSession:
    """Parse the AI-Music-Generation-README.md into structured entries.

    The README has no generation entries (it's a reference doc). It yields:
    - taste_lessons from Core Musical Styles & Preferences and Vocal Preferences
    - suno_facts from Suno-Specific Technical Notes
    - templates from Quick Reference Prompts and Style Variation Templates
    """
    text = path.read_text(encoding="utf-8")
    session_id = "readme"
    session = ParsedSession(session_id=session_id, source_path=str(path))

    h2_sections = _split_sections(text, level=2)

    for h2 in h2_sections:
        heading_lower = h2.heading.lower()

        if "suno-specific" in heading_lower or "technical notes" in heading_lower:
            facts, _ = _parse_learning_section(h2.content, session_id, h2.heading)
            for bullet in _extract_bullets(h2.content):
                if len(bullet) > 10:
                    session.suno_facts.append(ParsedSunoFact(
                        statement=bullet,
                        topic_tags=_infer_suno_fact_tags(bullet),
                        confidence="high",
                    ))
            session.suno_facts.extend(facts)

        elif "prompt engineering" in heading_lower or "engineering principles" in heading_lower:
            # Check H3 subsections — e.g., "Suno-Specific Technical Notes" is H3 here
            for h3 in _split_sections(h2.content, level=3):
                h3_lower = h3.heading.lower()
                if "suno" in h3_lower or "technical" in h3_lower or "notes" in h3_lower:
                    for bullet in _extract_bullets(h3.content):
                        if len(bullet) > 10:
                            session.suno_facts.append(ParsedSunoFact(
                                statement=bullet,
                                topic_tags=_infer_suno_fact_tags(bullet),
                                confidence="high",
                            ))
                elif "golden rules" in h3_lower or "rules" in h3_lower:
                    # Golden rules are Suno facts too.
                    # Skip bold-only lines (numbered rule headings) — capture the
                    # sub-bullets that have the actual actionable content.
                    for bullet in _extract_bullets(h3.content):
                        # Filter out lines that are just bold headers (no real content)
                        clean = re.sub(r"\*\*(.+?)\*\*", r"\1", bullet).strip()
                        if len(clean) > 20 and not re.match(r"^(Instead|Example|Focus|Use|Combine|Technical|Always|Descriptive)", clean):
                            session.suno_facts.append(ParsedSunoFact(
                                statement=clean,
                                topic_tags=["prompt_construction"],
                                confidence="high",
                            ))

        elif any(kw in heading_lower for kw in [
            "core musical styles", "vocal", "language preferences", "mood"
        ]):
            # Taste lessons — README-derived are explicit (no user confirmation needed)
            for bullet in _extract_bullets(h2.content):
                if len(bullet) > 10:
                    valence = "positive"  # README only records preferences, not dislikes
                    scope: str = "general"
                    if re.search(r"genre|style|jazz|lo.?fi|hip.?hop", bullet, re.IGNORECASE):
                        scope = "genre"
                    elif re.search(r"vocal|voice|breath|smoky", bullet, re.IGNORECASE):
                        scope = "vocal"
                    elif re.search(r"texture|production|analog|vinyl|tape", bullet, re.IGNORECASE):
                        scope = "production"
                    session.taste_lessons.append(ParsedTasteLesson(
                        statement=bullet,
                        valence=valence,
                        scope=scope,
                        session_id=session_id,
                        is_explicit=True,
                    ))

        elif any(kw in heading_lower for kw in [
            "quick reference prompts", "style variation templates", "prompt engineering"
        ]):
            # Parse named templates. Three layouts to handle:
            # 1. H3 sub-sections with code blocks
            # 2. **Bold:** labels immediately before code blocks (README Quick Reference)
            # 3. Free code blocks (fallback)

            seen_patterns: set[str] = set()

            def _add_template_if_new(name: str, block: str, is_explicit: bool = True) -> None:
                key = block.strip()[:100]
                if key in seen_patterns or len(block) < 20:
                    return
                seen_patterns.add(key)
                swap_vars = _extract_swap_variables(block)
                descriptor = _derive_template_descriptor(block, name)
                session.templates.append(ParsedTemplate(
                    name=name.strip(),
                    descriptor=descriptor,
                    style_pattern=block,
                    swap_variables=swap_vars,
                    source_session_id=session_id,
                    is_explicit=is_explicit,
                ))

            # H3 sub-sections
            h3_sections = _split_sections(h2.content, level=3)
            for h3 in h3_sections:
                blocks = _extract_code_blocks(h3.content)
                if blocks:
                    _add_template_if_new(h3.heading, blocks[0])

            # Bold-label patterns: **Name:** followed by a code block
            # Scan the H2 content line by line
            lines = h2.content.splitlines()
            pending_bold_name: str | None = None
            j = 0
            while j < len(lines):
                line = lines[j].strip()
                bold_m = re.match(r"^\*\*(.+?)\*\*:?\s*$", line)
                if bold_m:
                    pending_bold_name = bold_m.group(1).strip()
                elif line.startswith("```") and pending_bold_name:
                    end = j + 1
                    while end < len(lines) and not lines[end].strip().startswith("```"):
                        end += 1
                    block_text = "\n".join(lines[j + 1:end]).strip()
                    if block_text:
                        _add_template_if_new(pending_bold_name, block_text)
                    pending_bold_name = None
                    j = end
                elif line and not line.startswith("```"):
                    # Non-empty, non-code line resets the pending bold name
                    if not re.match(r"^\*\*", line):
                        pending_bold_name = None
                j += 1

            # Remaining free code blocks (fallback, only if not already seen)
            free_blocks = _extract_code_blocks(h2.content)
            for block in free_blocks:
                _add_template_if_new(h2.heading.strip(), block)

    return _deduplicate_session(session)


# ── File 7 — reference collection parser ─────────────────────────────────────
# File 7 (Lo-Fi Hip-Hop & Cozy Game Music) was confirmed to have been run in
# Suno. Its 14 prompts are stored as generation entries with reaction="liked".
# The "Quick Reference: Mood to Prompt" table and Key Learnings are parsed
# normally (taste + suno_facts).


# ── Template descriptor derivation ───────────────────────────────────────────

def _derive_template_descriptor(style_text: str, heading: str) -> str:
    """Generate a short descriptor for a template from its heading and content."""
    # Use the heading as the primary descriptor, normalised
    clean_heading = re.sub(r"[^a-zA-Z0-9 ,/-]", "", heading).strip()
    if len(clean_heading) > 10:
        return clean_heading[:120]
    # Fall back to first comma-clause of the style text
    first_clause = style_text.split(",")[0].strip()
    return first_clause[:120]


def _infer_suno_fact_tags(statement: str) -> list[str]:
    tags: list[str] = []
    if re.search(r"lyric|vocal|voice|\[Instrumental\]|language", statement, re.IGNORECASE):
        tags.append("vocal_control")
    if re.search(r"character limit|1000|length|field", statement, re.IGNORECASE):
        tags.append("style_field")
    if re.search(r"\[.+\]|bracket|tag|marker|section", statement, re.IGNORECASE):
        tags.append("structure_tags")
    if re.search(r"bpm|tempo|speed|duration", statement, re.IGNORECASE):
        tags.append("tempo")
    if re.search(r"track length|extend|chain", statement, re.IGNORECASE):
        tags.append("track_length")
    return tags


# ── Session-level post-processing ────────────────────────────────────────────

def _apply_session_post_processing(session: ParsedSession, source_text: str) -> ParsedSession:
    """Post-processing passes that require whole-session context.

    1. "Same Style as Version N" inheritance: copy style_field from referenced version.
    2. Session-level chain detection: "Iteration N" H2 headers → linear chain.
    3. Re-check for missing prompt 10 patterns (styles defined by reference, lyrics only).
    """
    prompts = session.prompts

    # Pass 1: detect and inherit "Same Style as Version N"
    # Scan the source text for H3 sections that have "Same Style as" but no style code block.
    # "Version N" in this context refers to the N-th version WITHIN THE SUB-SERIES, not
    # to the overall prompt index — so we look for a prompt whose name ends with "Version N".
    same_style_re = re.compile(
        r"^(#{2,4})\s+(\d+)\..+?$",
        re.MULTILINE,
    )
    for h_match in same_style_re.finditer(source_text):
        section_num = int(h_match.group(2))
        # Check if this section references "Same Style as Version N"
        start = h_match.end()
        # Find end of this section (next same-level heading or EOF)
        hashes = h_match.group(1)
        end_pat = re.compile(rf"^{re.escape(hashes)}\s+\d+\.", re.MULTILINE)
        end_m = end_pat.search(source_text, start)
        section_content = source_text[start: end_m.start() if end_m else len(source_text)]

        same_style_m = re.search(
            r"[Ss]ame [Ss]tyle as (?:Version\s+)?#?(\d+)", section_content
        )
        if not same_style_m:
            continue

        ref_version = same_style_m.group(1)
        # This section should produce prompt at section_num-1 (0-indexed).
        # But it may not have a style code block.
        # Check if we already have a prompt for this section number in our list.
        already_have = any(
            re.search(rf"\b{section_num}\b", p.name) or
            (p.suggested_track_title and re.search(rf"\b{section_num}\b", p.suggested_track_title))
            for p in prompts
        )
        if already_have:
            continue

        # Find the referenced style source: look for a prompt named "Version {ref_version}"
        ref_prompt: ParsedPrompt | None = None
        for p in reversed(prompts):
            if re.search(rf"Version\s*{ref_version}\b", p.name, re.IGNORECASE):
                ref_prompt = p
                break
        # Fall back to the previous prompt if no named match
        if ref_prompt is None and prompts:
            ref_prompt = prompts[-1]
        if ref_prompt is None:
            continue

        # Extract lyrics from this section
        lyrics_blocks = _extract_code_blocks(section_content)
        if not lyrics_blocks:
            continue

        # Get heading text
        heading_m = re.match(rf"^{re.escape(hashes)}\s+\d+\.\s+(.+?)$", h_match.group(0), re.MULTILINE)
        heading_text = heading_m.group(1).strip() if heading_m else h_match.group(0).strip()
        clean_name = _strip_reaction_markers(heading_text)

        reaction = _infer_reaction(h_match.group(0) + " " + section_content[:200])

        # Find the parent index (the ref prompt's position)
        ref_idx = next(
            (i for i, p in enumerate(prompts) if p is ref_prompt), len(prompts) - 1
        )

        prompts.append(ParsedPrompt(
            session_id=session.session_id,
            name=clean_name,
            style_field=ref_prompt.style_field,
            lyrics_field=lyrics_blocks[0].strip(),
            reaction=reaction,
            bpm=ref_prompt.bpm,
            language=ref_prompt.language,
            suggested_track_title=clean_name[:50],
            change_summary=f"Same style as Version {ref_version}; different lyrics",
            parent_index=ref_idx,
        ))

    # Pass 2: session-level iteration chain detection
    # If ALL prompt names start with "Iteration N" pattern, set up linear chain
    iteration_re = re.compile(r"^Iteration\s+(\d+)\b", re.IGNORECASE)
    if prompts and all(iteration_re.match(p.name) for p in prompts):
        for i, prompt in enumerate(prompts):
            if i > 0:
                prompts[i] = prompt.model_copy(update={"parent_index": i - 1})

    session.prompts = prompts
    return session


# ── Deduplication ─────────────────────────────────────────────────────────────

def _deduplicate_session(session: ParsedSession) -> ParsedSession:
    """Remove duplicate suno_facts and taste_lessons by statement text."""
    seen_facts: set[str] = set()
    unique_facts: list[ParsedSunoFact] = []
    for f in session.suno_facts:
        key = f.statement.lower().strip()
        if key not in seen_facts and len(key) > 10:
            seen_facts.add(key)
            unique_facts.append(f)
    session.suno_facts = unique_facts

    seen_taste: set[str] = set()
    unique_taste: list[ParsedTasteLesson] = []
    for t in session.taste_lessons:
        key = t.statement.lower().strip()
        if key not in seen_taste and len(key) > 10:
            seen_taste.add(key)
            unique_taste.append(t)
    session.taste_lessons = unique_taste

    seen_templates: set[str] = set()
    unique_templates: list[ParsedTemplate] = []
    for t in session.templates:
        key = t.style_pattern.strip()[:100]
        if key not in seen_templates and t.name.strip():
            seen_templates.add(key)
            unique_templates.append(t)
    session.templates = unique_templates

    return session


# ── Public entry point ────────────────────────────────────────────────────────

def parse_file(path: Path) -> ParsedSession:
    """Parse any seed file (README or session file)."""
    if path.name == "AI-Music-Generation-README.md":
        return parse_readme(path)
    return parse_session_file(path)


def parse_directory(directory: Path) -> list[ParsedSession]:
    """Parse all markdown files in a directory, README first."""
    md_files = sorted(directory.glob("*.md"))
    readme_files = [f for f in md_files if f.name == "AI-Music-Generation-README.md"]
    session_files = [f for f in md_files if f.name != "AI-Music-Generation-README.md"]
    ordered = readme_files + sorted(session_files)
    return [parse_file(f) for f in ordered]
