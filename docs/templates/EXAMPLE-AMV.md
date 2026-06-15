---
title: Example Project Flow — AMV / Anime Mashup
date: 2026-06-12
type: example-flow
project: agent-stack
status: active
tags:
  - example
  - workflow
  - amv
---

# Example Project Flow: AMV / Anime Mashup

The originating use case for the system. Deliverable: a short anime music video (~90 seconds) cutting sourced anime footage to a generated track, with optional voiceover and generated imagery (character stills, thumbnail). This is the fullest flow — every production agent participates.

No agent forces this sequence. Steps can be skipped, reordered, or repeated; this is the typical full run. Any free (non-side-effecting) step can also be driven conversationally through `orchestrator chat`.

**Running example:** "Demon Slayer + phonk + ~90 seconds + revenge mood."

## Step 1 — Define the theme

**Primary agent:** Director (manual)

Decide the creative core: source anime, musical direction, target length, mood. This is taste, not agent work — everything downstream consumes it.

## Step 2 — Research the craft

**Primary agent:** Technique Research (delegates to Tutorial Research)

Answer "what makes an effective AMV?" The agent grounds the reference, identifies prioritized technique domains, checks existing knowledge, and — behind an interactive cost gate — delegates gaps to Tutorial Research for gathering. Output: an editable `TechniqueReport` plus findings accumulated in `technique_research_outputs` (which Edit Brief and Visual Generation retrieve later automatically).

```bash
uv run technique-research identify "an AMV for Demon Slayer with a revenge mood, cut to phonk" -o techniques.md
```

## Step 3 — Write the script

**Primary agent:** Concept & Script

Turn the theme (plus the technique report as seed material) into the editable `script.md`: logline, sections, inline `[emotion]` tags, and a music-hint block for Music Curation. Use `draft` from sparse seeds, or `shape` from a voice-dictation transcript. The director then edits the file — the agent surfaces structure, the director decides.

```bash
uv run concept-script draft "Demon Slayer revenge AMV, phonk, ~90s" --seeds techniques.md -o script.md
```

## Step 4 — Craft the music

**Primary agent:** Music Curation

Translate the script's music hint into Suno prompts with style-tag breakdowns and music-theory reasoning, cross-referenced against prior generations in memory so liked directions are reproducible.

```bash
uv run music-curation generate "dark phonk, revenge mood, ~90s arc matching script.md's music hint"
```

## Step 5 — Generate and select the track

**Primary agent:** Director (manual — Suno has no API)

Run the prompts in Suno, listen, pick the track. Log the outcome so the direction is reproducible next time:

```bash
uv run music-curation report <gen_id> --reaction liked --rating 4
```

## Step 6 — Direct the voiceover

**Primary agent:** Voiceover Direction

Consume `script.md` unchanged and produce the editable directed script — audio tags inline, per-section voice/model/settings metadata. Direction is free and infinitely iterable; edit until settled.

```bash
uv run voiceover-direction direct script.md -o directed.md
```

## Step 7 — Generate the voiceover audio

**Primary agent:** Voiceover Direction (spend gate) + Director (listens, reacts)

Generation burns the monthly ElevenLabs character budget, so it is a deliberate commitment behind a soft-inform gate. Listen to the takes, then report reactions (`disliked` = wrong direction; `render_failed` = direction fine, render missed).

```bash
uv run voiceover-direction generate directed.md --all
uv run voiceover-direction report <take_id> --reaction loved
```

## Step 8 — Generate visual assets

**Primary agent:** Visual Generation

Character imagery and the thumbnail: free prompt-craft into a batch file, then GPU generation on the RunPod/ComfyUI pod behind its own soft-inform cost gate. Generated stills feed Edit Brief as available assets.

```bash
uv run visual-generation draft "Demon Slayer-styled revenge imagery + thumbnail" -o visual-batch.md --project demon-slayer-amv
uv run visual-generation generate visual-batch.md --all --endpoint <comfyui-url>
uv run visual-generation report <gen_id> --reaction liked
```

## Step 9 — Source the footage

**Primary agent:** Director (manual — rights and taste)

Download and organize the anime footage into a folder. This is deliberately never agent work.

## Step 10 — Build the edit brief

**Primary agent:** Edit Brief

Assemble everything into a time-ordered execution checklist for DaVinci Resolve free: section timestamps computed from VO take durations, a beat grid computed from the track's BPM, per-section checkbox steps grounded in the technique findings. VO takes, music, and generated assets are discovered from the collections by `project_id`; footage is the one flag-passed input.

```bash
uv run edit-brief draft script.md --footage ./footage --music ./track.mp3 -o edit-brief.md
```

## Step 11 — Edit

**Primary agent:** Director (manual)

Cut the video in DaVinci Resolve, working through the brief's checklist. The agents prepared the briefing; the director does the editing.

## Step 12 — Iterate on feedback

**Primary agent:** Feedback & Iteration

Watch the draft, give natural-language feedback ("the drop at 0:45 lands late, the middle drags"). The agent maps feedback to brief moments, patches the brief in place (version bumped, checkboxes preserved), and proposes durable lessons into `user_knowledge` via propose→confirm. Repeat steps 11–12 until satisfied.

```bash
uv run feedback-iteration revise edit-brief.md "the drop lands late and the middle section drags"
```

## Step 13 — Export and publish

**Primary agent:** Director (manual)

Final export approval and platform publishing — quality control and account ownership stay with the director.
