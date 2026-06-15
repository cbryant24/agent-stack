---
title: Example Project Flow — Video Game Review
date: 2026-06-12
type: example-flow
project: agent-stack
status: active
tags:
  - example
  - workflow
  - game-review
---

# Example Project Flow: Video Game Review

Deliverable: a narrated game review video. The structural difference from the AMV flow: **voiceover is the spine** — the script and narration carry the video, gameplay footage illustrates it, and music plays a supporting role (intro/background) rather than driving the cut.

No agent forces this sequence; steps can be skipped, reordered, or repeated. Free steps can also run through `orchestrator chat`.

**Running example:** a review of an indie roguelike, ~8 minutes, "measured but enthusiastic" tone.

## Step 1 — Play the game and form the thesis

**Primary agent:** Director (manual)

The opinion is the product. Play enough to have a verdict, the 3–4 points that support it, and the moments worth showing.

## Step 2 — Research the format

**Primary agent:** Technique Research (delegates to Tutorial Research)

"What makes a compelling game review video?" — structure conventions (hook, verdict placement, segment ordering), pacing against narration, b-roll technique. Findings accumulate in `technique_research_outputs` for Edit Brief to retrieve later.

```bash
uv run technique-research identify "an 8-minute indie game review video with a strong hook and clear verdict" -o techniques.md
```

## Step 3 — Write the script

**Primary agent:** Concept & Script

For reviews, `shape` mode is the natural fit: dictate impressions of the game stream-of-consciousness, and the agent extracts sections, preserves natural stumbles as authentic narration, executes `director note` edits, and applies inline emotion direction. (`draft` from seeds works too.) The director edits the resulting `script.md` — the argument and verdict are never the agent's call.

```bash
uv run concept-script shape story.md -o script.md
```

## Step 4 — Direct the voiceover

**Primary agent:** Voiceover Direction

The narration is most of the video, so this is the heaviest agent step. Direction (voice choice, emotion tags, pacing per section) is free and iterated until settled.

```bash
uv run voiceover-direction direct script.md -o directed.md
```

## Step 5 — Generate the narration

**Primary agent:** Voiceover Direction (spend gate) + Director (listens, reacts)

An 8-minute script is a meaningful chunk of the monthly ElevenLabs character budget — generate section by section behind the soft-inform gate rather than all at once, reporting reactions as you go so re-directs compound.

```bash
uv run voiceover-direction generate directed.md --section <id>
uv run voiceover-direction report <take_id> --reaction liked_with_changes --note "verdict section needs more weight"
```

## Step 6 — Curate supporting music

**Primary agent:** Music Curation

Intro sting and low-key background beds that sit under narration without fighting it. Lighter role than in the AMV flow, same loop: prompts → Suno (manual) → log the reaction.

```bash
uv run music-curation generate "understated lo-fi background bed that sits under spoken narration, plus a short energetic intro sting"
uv run music-curation report <gen_id> --reaction liked
```

## Step 7 — Capture gameplay footage

**Primary agent:** Director (manual)

Record the gameplay that illustrates each scripted point — the moments identified in Step 1. Organize clips into a folder, ideally named by the script section they support.

## Step 8 — Optional: thumbnail and graphics

**Primary agent:** Visual Generation

Thumbnail and any title/segment cards via the draft → generate → report loop on the ComfyUI pod. Optional — skip if screenshots suffice.

```bash
uv run visual-generation draft "bold game-review thumbnail for an indie roguelike, readable at small size" -o visual-batch.md
uv run visual-generation generate visual-batch.md --all --endpoint <comfyui-url>
```

## Step 9 — Build the edit brief

**Primary agent:** Edit Brief

The timeline skeleton comes from the narration takes — section timestamps from VO durations — with footage mapped to sections and the format findings placed against the grid. Music is a supporting layer here, so the beat grid matters less than in the AMV flow.

```bash
uv run edit-brief draft script.md --footage ./gameplay --music ./background-bed.mp3 -o edit-brief.md
```

## Step 10 — Edit

**Primary agent:** Director (manual)

Assemble in DaVinci Resolve following the brief: narration first, footage against it, music underneath.

## Step 11 — Iterate on feedback

**Primary agent:** Feedback & Iteration

Watch the draft and react in plain language ("the hook takes too long, the verdict gets buried"). The brief is patched in place with a version log; generalizable preferences become proposed lessons. Repeat 10–11 until satisfied.

```bash
uv run feedback-iteration revise edit-brief.md "the hook takes too long to get to the point"
```

## Step 12 — Export and publish

**Primary agent:** Director (manual)

Final export approval and upload.
