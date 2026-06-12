---
title: Example Project Flow — Music Exploration
date: 2026-06-12
type: example-flow
project: agent-stack
status: active
tags:
  - example
  - workflow
  - music-exploration
---

# Example Project Flow: Music Exploration

The shortest flow: standalone Music Curation, no video attached. Deliverable: finished Suno tracks plus — just as valuable — an accumulated memory of what was tried, what worked, and why, so good directions are reproducible in any future session or project. This is the flow that directly solves the original pain points: no continuity between sessions, drifting prompts, Suno misunderstandings.

One agent carries the whole loop; the director is the taste. Free steps (`recall`, `review-pending`) can also run through `orchestrator chat`.

**Running example:** exploring a "late-night synthwave with breakbeat edges" direction.

## Step 1 — Set the intent

**Primary agent:** Director (manual)

A vibe to chase, a reference to emulate (song, artist, film scene), or a prior direction to push further. As loose or specific as you like — the agent's job is to translate it.

## Step 2 — Recall prior territory

**Primary agent:** Music Curation

Before generating, check what memory already holds near this direction: prior generations, reactions, taste lessons. This is what makes session N+1 better than session N — iterating on a liked direction instead of restarting from zero.

```bash
uv run music-curation recall "late-night synthwave, breakbeat"
```

## Step 3 — Generate prompts

**Primary agent:** Music Curation

One or more Suno prompts with style-tag breakdowns and the music-theory reasoning behind each choice — so you learn the vocabulary and give better direction next round. Prompts are grounded in current Suno-feature knowledge (kept fresh via Tutorial Research delegation) and cross-referenced against similar prior generations.

```bash
uv run music-curation generate "late-night synthwave with breakbeat edges, nostalgic but driving, ~3 minutes"
```

## Step 4 — Run the prompts in Suno

**Primary agent:** Director (manual — Suno has no API)

Paste the prompts into Suno, generate, listen. Taste is the director's job; pick what's worth keeping or iterating on.

## Step 5 — Report back

**Primary agent:** Music Curation

Close the loop: log which prompt was used and the reaction. This is the step that builds the memory everything else depends on — skip it and the session evaporates like the old Claude-chat workflow did.

```bash
uv run music-curation report <gen_id> --reaction liked --rating 4
```

## Step 6 — Iterate

**Primary agent:** Music Curation + Director

Push the direction: "like the last one but darker, half-time drop." The agent pulls the logged generation, reasons about what to change musically, and emits the next prompt round. Repeat steps 3–5 until the direction is exhausted or a keeper lands.

```bash
uv run music-curation generate "iterate on <gen_id>: darker, half-time drop in the back third"
```

## Step 7 — Curate the memory

**Primary agent:** Music Curation (propose→confirm) + Director

When a durable preference crystallizes ("gated reverb snares read as parody to me — avoid"), store it deliberately. Memory is curated, not auto-harvested; the agent asks before storing. Review anything pending:

```bash
uv run music-curation taste add "gated reverb snares read as parody — avoid" --valence negative --scope production
uv run music-curation review-pending
```

## Done

There is no export step — the tracks live in Suno and the direction lives in `music_curation_memory`. The next session, or the next video project's Step "Craft the music," starts from this accumulated state instead of from zero.
