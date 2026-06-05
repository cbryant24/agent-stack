# voiceover-direction — Phase 1 research signals

These close the cold-start knowledge gap before Phase 2 begins. Two collections get seeded by two different paths:

- **`user_knowledge` (`domain="elevenlabs_mechanics"`)** — ElevenLabs' own docs. Authoritative ground truth for tag syntax, models, credits, and API mechanics. You collect these as markdown; the `knowledge ingest-docs` command (a Phase 2 build item) ingests them.
- **`tutorial_research`** — direction theory and practical tag-usage know-how that the docs don't teach. Populated by running the `tutorial-research` agent directly.

---

## A. ElevenLabs docs to collect as markdown → `user_knowledge`

Save each page's content as a markdown file in a single folder (e.g. `~/agent-data/sources/elevenlabs-docs/`). The agent does **not** fetch these — you collect them. Ingestion happens after Phase 2 builds `voiceover-direction knowledge ingest-docs <folder>`, so this is a "collect now, ingest after the command exists" signal.

These are the mechanics the agent must not get wrong, grouped by what they cover.

**Core model + credit mechanics**
- https://elevenlabs.io/docs/overview/intro — credits = one per character; monthly reset; rollover up to two months; voice IDs; model overview.
- https://elevenlabs.io/docs/overview/models — `eleven_v3` (expressive, audio tags), `eleven_flash_v2_5`, deprecations, concurrency.

**Prompting, audio tags, delivery control**
- https://elevenlabs.io/docs/overview/capabilities/text-to-speech/best-practices — delivery, pronunciation, emotion, `<break>` usage, v3 prompting notes.
- https://help.elevenlabs.io/hc/en-us/articles/35869142561297-How-do-audio-tags-work-with-Eleven-v3 — audio-tag categories (emotion / delivery direction / human reactions) and syntax.

**API mechanics the agent calls directly**
- https://elevenlabs.io/docs/api-reference/voices/get — voice object shape (id, name, category, labels, description) — backs `voice sync`.
- https://elevenlabs.io/docs/api-reference/user/subscription/get — subscription/usage fields, including the next character-count reset — backs the monthly character-budget query.
- The **Get character usage metrics** endpoint (under API reference → Administration → Usage) — per-period character usage. Capture this page too; it's the other half of the budget source-of-truth.

**Plan limits**
- https://elevenlabs.io/pricing — the free-plan monthly character allowance, so the soft-inform display reflects your actual ceiling.

> Note on currency: ElevenLabs' v3 / audio-tags surface is moving (v3 was in research-preview state as of the docs above). Re-check these pages when you collect them rather than trusting a cached version, and prefer the official `elevenlabs.io/docs` and `help.elevenlabs.io` pages over third-party tutorials for mechanics.

---

## B. `tutorial-research` runs → `tutorial_research`

Run these directly in iTerm2. They populate direction theory and practical know-how — the part docs don't cover. (Invocation form per the handoff; adjust flags to your tutorial-research CLI.)

```bash
tutorial-research "ElevenLabs v3 audio tags practical usage for voiceover"
```

```bash
tutorial-research "voiceover direction for YouTube videos pacing and tone"
```

```bash
tutorial-research "voice acting emotional pacing and delivery for narration"
```

```bash
tutorial-research "choosing and using AI voices for long-form narration"
```

Rationale for the split: the docs (Section A) give the agent authoritative *mechanics*; these runs give it *judgment* — how to map a section's intended tone to tag choices, where to pace, how to pick a voice for a narration style. That judgment is exactly what makes `direct` produce good markup, and it's what YouTube tutorials carry that vendor docs don't.

---

## If you skip a signal

The agent still runs — every retrieval leg degrades silently if its collection is thin. Skipping Section A means tag-syntax/credit knowledge comes only from tutorials (the weakest source for vendor mechanics). Skipping Section B means the agent directs from docs alone, with less feel for delivery. Neither blocks Phase 2; both lower output quality at first use.
