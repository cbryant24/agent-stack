---
title: Example Project Flow — Illustrated Narrated Short Story
date: 2026-06-13
type: example-flow
project: agent-stack
status: active
tags:
  - example
  - workflow
  - illustrated-story
  - short-film
---

# Example Project Flow: Illustrated Narrated Short Story

Deliverable: a short narrated story film carried by a single narrator, illustrated entirely by **generated stills** (no sourced footage), with **custom chapter songs** that comment on the story at key moments and an optional theatrical act-break structure (black-screen title cards, dramatic pauses). The structural difference from the other flows: **voiceover is the spine** like the game review, but every visual is generated rather than footage, and the music is an active storytelling device rather than a background bed. It needs no footage-sourcing step.

No agent forces this sequence; steps can be skipped, reordered, or repeated. Free steps can also run through `orchestrator chat`.

**Running example:** a funny-but-sincere ~3–4 minute story about a fast friendship, told in three acts, with chapter songs teasing the friend and a warm closing image. Project id: `illustrated-story`.

## Step 1 — Capture the creative brief

**Primary agent:** Director (manual)

Lock the creative core before any agent runs: the story, theme, references, inside jokes, the tone, and the ending image. This is taste, not agent work — everything downstream consumes it.

**Outcome:** a short `brief.md` (emotional core, references, key beats, intended ending).

## Step 2 — Research the format and style

**Primary agent:** Technique Research (delegates to Tutorial Research)

Answer "what makes an illustrated narrated short work?" — act-break pacing, dramatic-pause and title-card technique, how generated stills are paced against narration, where chapter songs land. Findings accumulate in `technique_research_outputs` for Visual Generation and Edit Brief to retrieve later.

```bash
uv run technique-research identify "a narrated illustrated short story in theatrical acts, voiceover spine, generated-still visuals, and short lyrical chapter songs" -o story-techniques.md
```

## Step 3 — Dictate (or write) the story

**Primary agent:** Director (manual)

Record or type the raw story. Don't over-polish — natural phrasing, jokes, asides, and any `director note` edit instructions are useful texture the next step preserves or resolves.

**Outcome:** `dictation-transcript.md` (or a written draft).

## Step 4 — Shape the script

**Primary agent:** Concept & Script

`shape` mode is built for dictated input: it extracts sections, an emotional arc, and inline `[emotion]` tags, preserves natural stumbles as authentic narration (or `--clean` resolves them into final prose), executes `director note` edits, and adds a music-hint block for the chapter songs. (`draft` from `brief.md` + the technique report works if you wrote rather than dictated.)

```bash
uv run concept-script shape dictation-transcript.md -o script.md
```

## Step 5 — Director script pass

**Primary agent:** Director (manual)

Edit `script.md` directly — keep the comedy from burying the sincerity, confirm the act beats and the closing line. The agent surfaces structure; the director decides the creative core.

## Step 6 — Craft chapter-song prompts

**Primary agent:** Music Curation

Translate the script's music hints into Suno prompts for short chapter songs that appear at act transitions and key moments — commentary, not a continuous bed. Style-tag breakdowns plus theory reasoning, cross-referenced against prior generations.

```bash
uv run music-curation generate "short chapter songs for a narrated illustrated story: playful teasing verses at act breaks, warm acoustic outro under the final scene, never overpowering narration"
```

## Step 7 — Generate and select the songs

**Primary agent:** Director (manual — Suno has no API) + Music Curation

Run the prompts in Suno, pick the songs or fragments for each act, and report the reaction so the direction is reproducible.

```bash
uv run music-curation report <gen_id> --reaction liked --rating 4 [--notes "..."]
```

## Step 8 — Direct the narration

**Primary agent:** Voiceover Direction

Consume `script.md` unchanged and produce the editable directed script — audio tags inline, per-section voice/model/settings. Thread the project id so takes are discoverable later. Direction is free and iterable; settle it before spending characters.

```bash
uv run voiceover-direction direct script.md -o directed.md --project-id illustrated-story
```

## Step 9 — Generate the narration takes

**Primary agent:** Voiceover Direction (spend gate) + Director (listens, reacts)

Generate section by section behind the soft-inform gate to manage the ElevenLabs character budget; report reactions so re-directs compound (`disliked` = wrong direction; `render_failed` = direction fine, render missed).

```bash
uv run voiceover-direction generate directed.md --section <id>
uv run voiceover-direction report <take_id> --reaction liked_with_changes [--rating 1-5] [--notes "warmer, less trailer-voice"]
```

## Step 10 — Draft the visual style and batch

**Primary agent:** Visual Generation

Free, iterable prompt-craft: define the recurring visual language (style, character likeness, recurring settings, the act-card look, the closing image) into a batch file with full settings recipes. Use the same project id so the stills auto-discover into the edit brief.

```bash
uv run visual-generation draft "<style + key scenes + character likeness + act cards + closing image>" -o batch.md --project illustrated-story
```

## Step 11 — Generate the stills

**Primary agent:** Visual Generation (spend gate) + Director (starts/stops pod)

Start the RunPod pod, sync the environment and register the workflow on first run, then generate behind the GPU cost gate.

```bash
uv run visual-generation model sync --endpoint <comfyui-url>
uv run visual-generation workflow register <exported-api.json>
uv run visual-generation generate batch.md --all --endpoint <comfyui-url> --max-session-cost <N>
```

## Step 12 — Review and report the stills

**Primary agent:** Director (taste) + Visual Generation (record)

Keep only the images that serve the story; report reactions to complete the generation records (prompt + settings → result → reaction) and accumulate reusable lessons.

```bash
uv run visual-generation report <gen_id> --reaction liked [--rating 1-5]
uv run visual-generation review-pending
```

## Step 13 — Build the edit brief

**Primary agent:** Edit Brief

Assemble into a time-ordered DaVinci Resolve checklist: section timestamps from the VO take durations, act-break and title-card placement, chapter songs as punctuation, stills mapped to sections. VO takes and stills are auto-discovered by `project_id`; pass the selected music with `--music`. (`--footage` is only for director-shot clips — there are none here.)

```bash
uv run edit-brief draft script.md --project-id illustrated-story --music ./chapter-songs.mp3 -o edit-brief.md
```

## Step 14 — Edit

**Primary agent:** Director (manual)

Cut in DaVinci Resolve following the brief: narration as the spine, act cards and dramatic pauses, stills placed to the grid (slow zooms/pans to give them motion), chapter songs at the transitions.

## Step 15 — Iterate on feedback

**Primary agent:** Feedback & Iteration

React to the draft in plain language; the brief is patched in place with a version log, and durable preferences become proposed lessons. Repeat steps 14–15 until satisfied.

```bash
uv run feedback-iteration revise edit-brief.md "the first act break needs a longer pause and the closing image should hold longer"
```

## Step 16 — Export and publish

**Primary agent:** Director (manual)

Final export approval and delivery — quality control and account ownership stay with the director.
