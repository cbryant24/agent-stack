---
title: Example Project Flow — Travel Vlog
date: 2026-06-12
type: example-flow
project: agent-stack
status: active
tags:
  - example
  - workflow
  - travel-vlog
---

# Example Project Flow: Travel Vlog

Deliverable: a narrated vlog cut from the director's own trip footage. The structural difference from the other video flows: this one is **footage-first** — the material already exists before any agent runs, and the script is shaped around what was actually captured rather than footage being sourced to match a script. Warmer VO direction, location-driven music, little or no generated imagery.

No agent forces this sequence; steps can be skipped, reordered, or repeated. Free steps can also run through `orchestrator chat`.

**Running example:** a week in Japan, ~6 minutes, reflective tone.

## Step 1 — The trip and the footage

**Primary agent:** Director (manual)

The footage exists before the project does. Offload, cull the unusable clips, and organize the keepers into a folder — roughly grouped by location or day.

## Step 2 — Dictate the story

**Primary agent:** Director (manual)

Watch through the footage and voice-record impressions as they come: what happened, what a place felt like, what surprised you. No structure needed — that's the next step's job. Transcribe the recording to a text file.

## Step 3 — Shape the script

**Primary agent:** Concept & Script

`shape` mode is built for exactly this input: the agent extracts the narrative latent in the rambling transcript — sections, pacing, inline emotion direction — while preserving natural stumbles and self-corrections verbatim as authentic vlog narration. Use `director note` wake phrases during dictation for deliberate edits. The director edits the resulting `script.md`.

```bash
uv run concept-script shape trip-dictation.md -o script.md
```

## Step 4 — Optional: research the format

**Primary agent:** Technique Research (delegates to Tutorial Research)

Worth running for the first vlog, skippable after: pacing conventions, montage technique, how strong travel vlogs balance narration against ambient footage. Findings persist in `technique_research_outputs`, so later vlogs get them for free.

```bash
uv run technique-research identify "a reflective 6-minute travel vlog balancing narration with ambient footage" -o vlog-techniques.md
```

## Step 5 — Curate the music

**Primary agent:** Music Curation

Mood beds per location or chapter — music that evokes place without overpowering narration. Prompts → Suno (manual) → log the pick.

```bash
uv run music-curation generate "warm reflective acoustic bed with Japanese instrumentation accents, sits under narration"
uv run music-curation report <gen_id> --reaction loved
```

## Step 6 — Direct and generate the voiceover

**Primary agent:** Voiceover Direction

Vlog narration wants a warmer, more conversational read than the other flows — direction is where that's dialed in, free, before any characters are spent. Then generate behind the soft-inform gate and report reactions.

```bash
uv run voiceover-direction direct script.md -o directed.md
uv run voiceover-direction generate directed.md --all
uv run voiceover-direction report <take_id> --reaction loved
```

## Step 7 — Build the edit brief

**Primary agent:** Edit Brief

Section timestamps from the VO takes, footage candidates ranked per section from the footage folder (descriptions as optional enrichment), music placed as chapter beds. Creative footage selection is surfaced, never decided — the brief proposes, the director picks.

```bash
uv run edit-brief draft script.md --footage ./japan-clips --music ./acoustic-bed.mp3 -o edit-brief.md
```

## Step 8 — Edit

**Primary agent:** Director (manual)

Cut in DaVinci Resolve following the brief — narration as the spine, footage selections from the ranked candidates, music under each chapter.

## Step 9 — Iterate on feedback

**Primary agent:** Feedback & Iteration

React to the draft in plain language ("the Kyoto section drags, the transition into Osaka is jarring"); the brief is patched in place with a version log, and durable preferences become proposed lessons. Repeat 8–9 until satisfied.

```bash
uv run feedback-iteration revise edit-brief.md "the Kyoto section drags and the Osaka transition is jarring"
```

## Step 10 — Export and publish

**Primary agent:** Director (manual)

Final export approval and upload.
