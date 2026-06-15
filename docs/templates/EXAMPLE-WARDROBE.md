---
title: Example Project Flow — Wardrobe / Visual Generation Engagement
date: 2026-06-12
type: example-flow
project: agent-stack
status: active
tags:
  - example
  - workflow
  - wardrobe-poc
  - visual-generation
---

# Example Project Flow: Wardrobe / Visual Generation Engagement

The `wardrobe-poc` shape: a visual-generation-centric project with no script, music, or voiceover. Deliverable: a curated set of generated stills — clothed wardrobe and scene variations on a consenting subject (the director himself), identity-locked via a character LoRA. The same flow applies to any stills-focused engagement; wardrobe is the concrete case.

**Scope boundary (hard line, carried from the engagement):** clothing/scene variation and creative generation only. Nude generation or clothed-to-unclothed transformation of real people is out of scope and not a capability the agent builds.

The cost structure drives the flow: prompt-craft is free and infinitely iterable; GPU pod uptime and generation runs are the spend. Pod lifecycle is Tier-1 advisory — the agent holds no RunPod key and prompts to stop on drain; starting and stopping the pod is the director's job.

**Running example:** a wardrobe variation set — same subject, same identity LoRA, across outfits and settings.

## Step 1 — Define the brief

**Primary agent:** Director (manual)

What variations, how many, what settings/moods, which reference images, what resolution and count. The brief plus the scope boundary above frame everything downstream.

## Step 2 — Start the pod

**Primary agent:** Director (manual — Tier-1 advisory)

Start the RunPod pod, launch ComfyUI, note the endpoint URL. The pod billing clock starts here; the discipline of the flow is to batch all free work before this step or keep the warm session tight.

## Step 3 — Sync the environment (first run / after pod changes)

**Primary agent:** Visual Generation

Pull the available models/LoRAs from the live pod into the local registry, and register the workflow graph(s) the batch will run (exported in API format, slot map confirmed propose→confirm).

```bash
uv run visual-generation model sync --endpoint <comfyui-url>
uv run visual-generation workflow register exported-api.json
```

## Step 4 — Draft the batch

**Primary agent:** Visual Generation

The free loop: translate the brief into prompts plus full settings recipes (model, sampler, steps, CFG, LoRA stack and strengths), each choice explained in plain language — the tutor role. Output is an editable batch file; iterate on it as long as needed, it costs nothing. Prior liked generations and technique lessons are retrieved from memory automatically.

```bash
uv run visual-generation draft "wardrobe variation set: <subject LoRA>, business / casual / outdoor settings, consistent identity, photoreal" -o visual-batch.md --project wardrobe-poc
```

## Step 5 — Generate

**Primary agent:** Visual Generation (spend gate)

The deliberate commitment: run the batch (or single sections) against the warm pod behind the soft-inform cost gate, with a session cost ceiling.

```bash
uv run visual-generation generate visual-batch.md --all --endpoint <comfyui-url> --max-session-cost 5
```

## Step 6 — Review and report

**Primary agent:** Director (taste) + Visual Generation (record)

Review the outputs, log reactions per generation. Reactions complete the generation records (prompt + settings + workflow → result → reaction) that make liked directions reproducible — the same prompt→result→reaction pattern as Music Curation.

```bash
uv run visual-generation report <gen_id> --reaction liked --rating 4
uv run visual-generation review-pending
```

## Step 7 — Iterate

**Primary agent:** Visual Generation

Move output toward the target: recall similar prior generations, fold what was learned into a revised batch, regenerate only the sections that need it. Settings insights worth keeping become explicit lessons; platform facts go to `user_knowledge`. Knowledge gaps (a new LoRA technique, a WAN setting) go through the explicit `research` command, which delegates to Tutorial Research on a child budget.

```bash
uv run visual-generation recall "outdoor lighting, photoreal full-body"
uv run visual-generation lesson add "identity LoRA above 0.9 fights outfit changes — keep 0.7-0.8 for wardrobe work" --scope settings --valence positive
uv run visual-generation research "Flux LoRA strength interaction with IP-Adapter"
```

Repeat steps 4–7 within the warm session; batch free work between sessions.

## Step 8 — Stop the pod

**Primary agent:** Director (manual — agent prompts on drain)

Stop the RunPod pod when the session ends. Until stop-automation (Tier-2, deferred) exists, this is the step that prevents silent spend.

## Step 9 — Curate and deliver

**Primary agent:** Director (manual)

Select the final set and deliver. Sensitive artifacts (the identity-bearing LoRA, generated outputs) stay protected at the storage/access layer.
