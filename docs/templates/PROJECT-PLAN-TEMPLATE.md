---
title: Project Plan Template — AI Director Agent System
date: 2026-06-13
type: project-template
project: agent-stack
status: active
tags:
  - template
  - workflow
  - project-planning
---

# Project Plan Template — AI Director Agent System

A blank, self-contained template **and** its own driver prompt. Fill in the **Objective** line below, paste this whole file into a chat LLM (Claude, Gemini, or ChatGPT), and the assistant interviews you to produce a **completed project plan**: a description of the project plus the ordered steps to take it to completion, which agent or tool runs each step, and a note where a requested capability does not yet exist.

This file carries everything the assistant needs inline — it does not assume access to the `agent-stack` repo or its docs.

---

## Objective

<!-- DIRECTOR: replace the bracketed line below with what you want to make, then paste this whole file (top to bottom, including the frontmatter) into a chat LLM. Leave everything else as-is. -->

**I want to make:** [DESCRIBE WHAT YOU WANT TO MAKE — e.g. "a ~3-minute illustrated short story with a voiceover and original background music, calm reflective tone, no sourced footage"]

---

<!-- ============================================================
     INSTRUCTIONS TO THE ASSISTANT — REMOVE THIS ENTIRE BLOCK
     (the "How to use this template" section) AND THE "Objective"
     section above FROM THE FINISHED PLAN.
     ============================================================ -->

## How to use this template *(instructions to the assistant — remove from the finished plan)*

You are helping a director plan a creative production project on the **AI Director Agent System** (`agent-stack`): a toolkit of standalone, domain-specialized agents the director composes per project. The director makes every creative decision; agents research, generate, and assemble. Your job is to turn the director's stated objective into a completed, ordered execution plan using only the capabilities defined in this file.

**HARD STOP — interview before output.** Do not write any part of the completed plan (frontmatter, project description, ordered steps — anything from Section C) in the same turn as your clarifying questions. Run the interview first, then *wait* for the director's answers, then assemble. If you catch yourself drafting steps before the director has answered, stop and ask instead. A fast, generic plan produced without the interview is the exact failure mode this template exists to prevent — surfacing options and one-shotting a plan are not the same thing.

Follow this protocol:

1. **Read the stated objective.** Take the director's goal from the **Objective** section above (the "I want to make:" line). If it's still the bracketed placeholder, ask the director to state their objective before doing anything else.

2. **Match to the closest example.** Compare the objective against **Section A — Examples catalog**. Name the closest-matching example and ask the director to paste in that example file (the `EXAMPLE-*.md` flow) so you can ground the plan in a known-good sequence. If none is close, say so and proceed from the capability sections directly.

3. **Walk the capability sections (Section B).** Each capability carries an **Include when** cue. For each one, decide:
   - **Include** — the objective clearly needs it.
   - **Drop** — it clearly does not apply (it will not appear in the finished plan).
   - **Ask** — it's genuinely ambiguous; ask **one** targeted clarifying question to decide. Do not ask about capabilities whose relevance is already obvious.
   Ask only the questions that change the plan. Group them if you can; keep the interview tight. When a question has a small set of natural answers, present them as concrete labeled options (A / B / C …) with a one-line description each, so the director can pick fast — then add any free-form notes.

4. **Handle not-yet-capable (v2) requests honestly.** If the objective requires a capability marked **v2 — not yet capable** (e.g. generated video clips), do **not** invent steps for it. State plainly in the finished plan that the project cannot be fully executed today, name the gap, and list the capabilities needed to close it. Offer the closest v1 alternative if one exists.

5. **Assemble the completed plan (Section C).** Only after the director has answered your clarifying questions (steps 2–3) — never before. Produce the finished document:
   - Author **project-relevant frontmatter** (not a fixed schema — see the frontmatter guidance below).
   - Write a short **project description** (deliverable, creative core, structural shape).
   - Produce the **ordered steps**, each with: the agent or tool (or "Director — manual"), what happens, the command to run, the expected outcome, and dependencies.
   - **Drop every unused capability section** — the finished plan contains only what this project uses.
   - Add a **"Not yet possible"** note only if a requested capability is v2.
   - **Remove this instruction block and every `Include when` cue** from the finished plan.

6. **Note free vs. spend.** Flag which steps are free/iterable (LLM-only direction) and which spend a scarce resource (ElevenLabs characters, GPU/pod time, manual Suno runs). The director commits to spend deliberately.

7. **Note the Orchestrator.** Any **free, non-side-effecting** step (recall, review, retrieval, planning) can also be driven conversationally through `orchestrator chat` instead of the individual CLI. Mention this where relevant; it is not itself a pipeline step.

8. **Pace the interview.** Ask your clarifying questions, then wait for the director's answers before continuing — do not answer them yourself. Surface options where useful, but never make the creative decisions (theme, message, which references matter); those belong to the director.

<!-- FINISHED-DOCUMENT FRONTMATTER GUIDANCE — REMOVE THIS COMMENT AND THE
     guidance paragraph below once you have authored real frontmatter.
     The finished plan's frontmatter is NOT standardized. Author whatever is
     most relevant to THIS project. Discard this template file's own frontmatter
     (its title/type/tags describe the template, not your project) and write
     fresh frontmatter for the plan. Useful candidates: title, date, project
     (agent-stack), type: project-plan, deliverable, running_example, the
     matched example, agents_used (list), spend_axes (elevenlabs/gpu/suno),
     status. Include only fields that carry meaning for this project. -->

---

## Section A — Examples catalog *(match the objective, then request the closest file)*

Short descriptions of every project flow currently documented. Use these to match the director's objective and ask them to paste in the closest `EXAMPLE-*.md`.

- **AMV / Anime Mashup** (`EXAMPLE-AMV.md`) — a short anime music video cutting sourced anime footage to a generated track, with optional voiceover and generated stills. **Music-driven cut.** The fullest flow; every production agent participates.
- **Music Exploration** (`EXAMPLE-MUSIC-EXPLORATION.md`) — standalone music creation, no video. Deliverable is finished Suno tracks plus accumulated taste memory. The shortest flow; Music Curation carries the whole loop.
- **Video Game Review** (`EXAMPLE-GAME-REVIEW.md`) — a narrated review video. **Voiceover is the spine**; gameplay footage illustrates; music plays a supporting (intro/background) role.
- **Travel Vlog** (`EXAMPLE-TRAVEL-VLOG.md`) — a narrated vlog cut from the director's own trip footage. **Footage-first**: the material exists before any agent runs and the script is shaped to it. Warm VO, location music, little or no generated imagery.
- **Wardrobe / Visual Generation** (`EXAMPLE-WARDROBE.md`) — a stills-only engagement: no script, music, or voiceover. Curated generated stills (clothed wardrobe + scene variation), identity-locked via a character LoRA. Visual-Generation-centric.
- **Illustrated Narrated Short Story** (`EXAMPLE-ILLUSTRATED-STORY.md`) — a narrated short story film. **Voiceover is the spine**, every visual is a **generated still** (no sourced footage), and **custom chapter songs** comment on the story at key moments; optional theatrical act-break structure. The all-generated-visuals + active-music + no-footage shape.

If the objective blends two (e.g. "a short illustrated story with voiceover" ≈ Game Review's VO spine + Wardrobe's stills, minus footage), name the blend and pull the relevant capability sections from B.

**Sample outputs.** For concrete examples of what individual agent output *files* look like (as opposed to the `EXAMPLE-*.md` flow descriptions above), see `docs/templates/sample-outputs/`. It holds one real, chained run — `script-draft.md` (concept-script) → `script-draft.directed.md` (voiceover-direction) → `script-draft.edit-brief.md` (edit-brief). Consult or attach these when planning to ground expectations for each stage's deliverable.

---

## Section B — Capability sections *(standalone; include, drop, or ask per the cue)*

Each capability is self-contained. The system is a roster, not a fixed pipeline — include only what the objective needs. Default ordering across a full video project runs roughly: theme → technique research → script → music → voiceover → visual stills → (footage, director) → edit brief → edit (director) → feedback → export (director). State explicit dependencies, not a forced sequence.

---

### B1. Technique Research — `technique-research` *(v1 — capable)*

**Include when:** the objective is a video/visual type whose craft conventions matter and haven't been researched yet ("what makes an effective X?"). Drop for pure music exploration, or for a repeat format already researched.

**What it does:** Given a creative goal, identifies the prioritized technique domains that make "videos like X" work, checks existing knowledge, and — behind an interactive cost gate — delegates the actual gathering to Tutorial Research. Reasoning is vision-capable: it accepts optional reference image(s) and a reference video URL (metadata only). It owns the *relevance decisions*, not the raw material.

**Where in the flow:** early, before scripting. Feeds Concept & Script as seed material; its findings are retrieved automatically later by Visual Generation and Edit Brief.

**Inputs:** the creative goal (required); optional domain hint, reference image(s), reference video URL, a prior report (`--ref`), and a scope hint (`editing | generation | both`).

**Expected outcome:** an editable `TechniqueReport` markdown file the director owns, plus per-technique findings accumulating in the shared knowledge base.

**How to run it:**
```bash
uv run technique-research identify "<goal, e.g. an 8-minute indie game review with a strong hook>" -o <name>-techniques.md
```

**Director (manual) part:** none required; the director edits the report if desired.

---

### B2. Concept & Script — `concept-script` *(v1 — capable)*

**Include when:** the project has narration, spoken content, or any structured script. Drop for music-only exploration and stills-only engagements (e.g. wardrobe).

**What it does:** Turns sparse creative seeds **or** a verbatim voice-dictation transcript into a single editable `script.md` — logline, sections, inline `[emotion]` tags, and an optional music-hint block. It *surfaces* craft scaffolding (sectioning, pacing, an emotional arc); the director *decides* the creative core by editing the file. Its output **is** the file the Voiceover Direction agent consumes unchanged.

**Two modes:**
- **`draft`** (generative) — from sparse seeds (theme, mood, target length, references), optionally seeded by a technique report.
- **`shape`** (curation) — from a verbatim dictation transcript; extracts structure, preserves natural stumbles/self-corrections as authentic narration by default (`--clean` resolves them into final prose), and executes `director note` wake-phrase edits.

**Where in the flow:** after theme/technique research, before voiceover and music. The script's music-hint block feeds Music Curation.

**Inputs:** seeds (text or a `--seeds` file) for `draft`; a transcript file for `shape`; optional `--ref` to a prior script.

**Expected outcome:** an editable `script.md` the director owns and edits.

**How to run it:**
```bash
uv run concept-script draft "<seeds>" --seeds <techniques.md> -o script.md      # generative
uv run concept-script shape <dictation-transcript.md> -o script.md [--clean]     # curation
```

**Director (manual) part:** edits `script.md` — the argument, message, and which references matter are never the agent's call.

---

### B3. Music Curation — `music-curation` *(v1 — capable)*

**Include when:** the project needs custom music — a driving track (AMV), a supporting bed (review, vlog), or standalone tracks (music exploration). Drop if all audio is sourced elsewhere or there is no music.

**What it does:** A music-theory expert with persistent memory that translates intent into **Suno prompts** with style-tag breakdowns and the reasoning behind each choice, cross-referenced against prior generations so liked directions are reproducible. Suno has no public API — the agent emits prompts; the director runs them in Suno and reports back.

**Where in the flow:** after the script (so the music-hint informs it), or standalone. The reported reaction builds the memory that makes the next session start ahead of zero.

**Inputs:** stated mood/vibe, reference tracks/artists/films, optional music-hint from the script, references to prior liked generations.

**Expected outcome:** one or more Suno prompts + theory reasoning; after the director reports back, a logged generation entry (prompt → result → reaction).

**How to run it:**
```bash
uv run music-curation recall "<query>"                                  # check prior territory first
uv run music-curation generate "<request, e.g. dark phonk, ~90s arc>"   # emit prompts
uv run music-curation report <gen_id> --reaction <loved|liked|...> [--rating 1-5] [--notes "..."]
```

**Director (manual) part:** runs the prompts in Suno, listens, picks the track, then reports the reaction. **Manual spend step** (Suno generations).

---

### B4. Voiceover Direction — `voiceover-direction` *(v1 — capable)*

**Include when:** the project has spoken narration or character voice. Drop for music-only, AMV-without-VO, and stills-only projects.

**What it does:** Consumes `script.md` unchanged and produces an editable **directed script** (audio tags inline, per-section voice/model/settings). Direction is free LLM iteration; **generation** (the ElevenLabs TTS call) burns a scarce monthly character budget, so it's a deliberate commitment behind a soft-inform gate. Iterate freely in direction; spend characters once settled.

**Where in the flow:** after the script, parallel to music. Its take durations feed Edit Brief's timeline.

**Inputs:** `script.md` (markdown with headings); voice references and intended delivery shape the direction.

**Expected outcome:** an editable `directed.md`; then generated audio files + `take` records (born `pending` until the director reacts); recorded reactions accumulate direction lessons.

**How to run it:**
```bash
uv run voiceover-direction direct script.md -o directed.md                 # free, iterable
uv run voiceover-direction generate directed.md (--all | --section <id>)   # spends characters
uv run voiceover-direction report <take_id> --reaction <loved|liked|liked_with_changes|disliked|render_failed> [--rating 1-5] [--notes "..."]
```

**Director (manual) part:** selects the voice from the ElevenLabs library; listens to takes and reports reactions. **Scarce spend** (monthly ElevenLabs character budget) — generate section-by-section for long scripts.

---

### B5. Visual Generation — Stills — `visual-generation` *(v1 — capable)*

**Include when:** the project needs generated imagery — character stills, thumbnails, title/segment cards, or a curated stills set (wardrobe). Drop when every visual is sourced footage.

**What it does:** A diffusion image generation collaborator and platform tutor. Free, infinitely iterable **prompt-craft** into a batch file with full settings recipes (model, sampler, steps, CFG, LoRA stack) explained in plain language; then **GPU generation** on a RunPod/ComfyUI pod behind a soft-inform cost gate. Models: **Flux.1 dev** (stills-first), **SDXL** checkpoints, **character LoRAs** for identity lock. Pod lifecycle is advisory — the agent holds no RunPod key; the director starts/stops the pod.

**Where in the flow:** after the script (for character/thumbnail intent) or standalone (wardrobe). Generated stills feed Edit Brief as available assets.

**Inputs:** creative intent (subject, style, mood, references); reference images; a character LoRA or intent to train one (training itself is deferred); target output (resolution, count).

**Expected outcome:** a batch file of prompts + settings recipes; generated assets via the ComfyUI API; generation records (prompt + settings → result → reaction) for reproducibility.

**How to run it:**
```bash
uv run visual-generation model sync --endpoint <comfyui-url>          # first run / after pod changes
uv run visual-generation workflow register <exported-api.json>
uv run visual-generation draft "<intent>" -o batch.md --project <id>  # free prompt-craft
uv run visual-generation generate batch.md --all --endpoint <comfyui-url> --max-session-cost <N>
uv run visual-generation report <gen_id> --reaction <loved|liked|liked_with_changes|disliked|render_failed> [--rating 1-5]
```

**Thread the project id:** use the same slug for `--project <id>` here as you pass to `edit-brief --project-id` so the generated stills auto-discover into the brief (don't pass stills to edit-brief as `--footage`).

**Director (manual) part:** starts and stops the RunPod pod (billing clock); reviews outputs and reports reactions. **Scarce spend** (GPU/pod uptime + per-run generation) — batch free prompt-craft before starting the pod. **Scope boundary:** clothing/scene variation and creative generation only; no nude generation or clothed-to-unclothed transformation of real people.

---

### B6. Video Generation — `visual-generation` (WAN 2.2) *(v2 — NOT yet capable)*

**Include when:** the objective requires **generated video/animation clips** (text-to-video, image-to-video, or video-to-video), as opposed to cutting existing footage.

**Status — not yet capable in v1.** The system generates stills (B5) but does not yet generate video. If the objective requires generated video, the finished plan must state the project **cannot be fully executed today**, name this gap, and offer the closest v1 path (e.g. generate stills and animate them manually in the editor, or source footage).

**Capabilities needed to enable it:** WAN 2.2 (T2V / I2V / VACE) workflow graphs registered on the ComfyUI pod; the `visual-generation generate` turn extended to drive and capture video outputs (the turn shape and multimodal keyframe+caption memory already exist — this is a fast-follow on the same path, not a redesign); and GPU budget sized for video runs (minutes of GPU per clip, far more than per still).

**How to run it:** *not available yet — no command.*

---

### B7. Edit Brief — `edit-brief` *(v1 — capable)*

**Include when:** the deliverable is an edited video assembled in DaVinci Resolve. Drop for music-only and stills-only deliverables.

**What it does:** Assembles the creative artifacts (script, music + BPM, voiceover takes, footage, generated assets, technique findings) into a director-owned, **time-ordered execution checklist** for a DaVinci Resolve *free* session. Its distinct competence is assembly and time-translation: section timestamps from VO durations, beat-aligned cut points from BPM, retrieved findings placed against the grid. **It does not touch the DaVinci API or edit anything** — it prepares the briefing.

**Where in the flow:** after the assets exist (script, VO, music, stills, footage), before the director edits.

**Inputs:** `script.md` (required); everything else discovered from collections by `project_id`, with overrides. VO takes and generated stills are **auto-discovered by `project_id`** (so thread the same id used by `voiceover-direction --project-id` and `visual-generation --project`); the selected music track is passed via `--music`; **`--footage DIR` is only for director-sourced video clips, not generated stills.**

**Expected outcome:** an editable `edit-brief.md` next to the script: a timeline skeleton, a beat grid, and per-section ordered checkbox steps executable in Resolve free.

**How to run it:**
```bash
uv run edit-brief draft script.md --project-id <id> --music ./track.mp3 [--footage ./clips] -o edit-brief.md
```

**Director (manual) part:** sources and organizes any director-shot footage into the folder (rights and taste — never agent work).

---

### B8. Feedback & Iteration — `feedback-iteration` *(v1 — capable)*

**Include when:** there is an edit brief to iterate on (pairs with B7). Drop if there's no edit brief.

**What it does:** Takes the director's natural-language reaction to a draft edit ("the drop lands late, the middle drags") and translates it into specific actionable changes, patching the live `edit-brief.md` **in place** (version bumped, checkboxes preserved) and proposing durable lessons. Tier 1 — no DaVinci API; every action is Resolve-free-executable. Timing shifts are recomputed in code, never LLM-estimated.

**Where in the flow:** after the first draft edit; loops with the director's editing pass until satisfied.

**Inputs:** the live `edit-brief.md` (required); feedback inline and/or `--feedback FILE`.

**Expected outcome:** the brief revised in place with a version-log entry; generalizable preferences become proposed lessons.

**How to run it:**
```bash
uv run feedback-iteration revise edit-brief.md "<plain-language feedback>"
```

**Director (manual) part:** watches the draft, gives feedback, re-edits in DaVinci between revisions.

---

### B9. Orchestrator — `orchestrator` *(v1 — cross-cutting, not a pipeline step)*

**Include when:** always worth noting, but never as a standalone production step. The Orchestrator is the conversational "director's console" — a system expert that answers questions, retrieves from the knowledge bases, reads the live codebase/docs, and can invoke the other agents' **free, non-side-effecting** operations as tools (so it can never trigger paid generation on its own).

**How it relates to the plan:** any free step in the plan (recall, review-pending, retrieval, technique identification, planning) can be driven through `orchestrator chat` instead of the individual CLI. Note this against the relevant steps; do not list it as its own step.

**How to run it:**
```bash
uv run orchestrator chat [--thread <id>]
```

---

## Section C — Assemble the completed plan *(the output you produce)*

Produce the finished document in this shape (and remove Sections A, B, and the instruction block — keep only what this project uses):

1. **Frontmatter** — project-relevant fields you authored (see the frontmatter guidance above). Not a fixed schema.

2. **Project description** — 2–4 sentences: the deliverable, the creative core, and the structural shape (what drives the cut — music, voiceover, or footage). Name the matched example if you used one.

3. **Spend & free map** — one short paragraph: which steps are free/iterable and which spend a scarce resource (manual Suno runs, ElevenLabs characters, GPU/pod time). The director commits to spend deliberately.

4. **Ordered steps** — the heart of the plan. For each step, in dependency order:
   - **Step N — `<title>`**
   - **Agent / tool:** the agent name, or "Director — manual," or "Orchestrator (free, conversational)."
   - **What happens:** one or two sentences.
   - **Command:** the exact CLI to run (omit for manual steps).
   - **Expected outcome:** the artifact or result.
   - **Depends on:** prior steps/artifacts, if any.

   Assembly rules:
   - **Open with a Director step** that captures the creative brief — story/theme, references, inside jokes, the ending — into a `brief.md` before any agent runs. The creative core is the director's, stated once up front; downstream steps consume it.
   - **Thread one `project_id`** through the whole plan: pick a slug and pass it to `voiceover-direction --project-id`, `visual-generation --project`, and `edit-brief --project-id` so takes and stills auto-discover. Pass the selected music to `edit-brief` via `--music`. Do not pass generated stills as `--footage`.
   - **Output paths — write director-owned files into the project folder.** Every `-o` output (`brief.md`, `script.md`, `directed.md`, the visual batch, `edit-brief.md`) goes in `~/agent-projects/<project-slug>/` (slug = the `project_id`). *Why:* these are director-owned working files, they belong together per project (edit-brief writes next to the script and discovers by `project_id`), and they must stay out of the personal vault, out of `agent-reports`, and out of any folder that gets ingested. You do **not** set paths for machine-managed outputs: generated audio/stills land in `~/agent-data/…` automatically, and run reports auto-write to `~/obsidian/agent-reports/`. (Canonical detail: the "File organization" section of the repo root README.)

5. **Not yet possible (only if applicable)** — if the objective requested a v2 capability (e.g. generated video), state the project cannot be fully executed today, name the gap, list the capabilities needed, and give the closest v1 alternative.

6. **Director tasks** — a short list of what stays with the director throughout (creative decisions, Suno selection, footage sourcing, voice selection, DaVinci editing, final export and publishing).

Save the finished plan to `docs/projects/<project-slug>-plan.md` (use the same slug as the `project_id`). Keep it tight: only the sections this project uses, real commands, explicit dependencies, no leftover template scaffolding.
