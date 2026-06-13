# Handoff: visual-generation agent — Phase 2

**Status:** Phase 1 (design and discovery) complete. Phase 2 is implementation.
**Predecessors:** agent-runtime, yt-intelligence-pipeline, tutorial-research, music-curation, voiceover-direction, concept-script — all complete.
**Date:** 2026-06-08

---

## How to start Phase 2 (read first)

You are executing **Phase 2 — implementation** of the visual-generation agent. You are Claude Chat: you do **not** write code directly. You draft the Claude Code prompts the user pastes into Claude Code, and you call out any CoWork scaffolding needed first (the established workflow: CoWork scaffolds a new package, Claude Code implements). The build methodology is in `docs/ai-director-agent-system.md`.

**Your first action — the first build session, in this order:**

1. A Claude Code prompt to **extract the `knowledge ingest-docs` flow into agent-runtime** as a shared mechanism and switch voiceover-direction to call it (behavior-preserving), re-running voiceover-direction's suite to confirm no regression. Existing packages — no scaffolding.
2. **CoWork scaffolding** for the new `visual-generation` package (directories, `pyproject`, README, initial module files).
3. A Claude Code prompt for the **visual-generation data foundation**: the `visual_generation_memory` collection + store wrapper, the three memory types (`generation` multimodal, `technique_lesson`, `workflow_template`), the model/LoRA registry, and the three-collection retrieval composition.

Confirm the build order with the user, then deliver step 1. Everything below is the design rationale — consume it, don't re-derive it.

---

## What this is

Phase 1's design conversation is done. Every design question (one central, eleven secondary) is resolved with reasoning, recorded below. Phase 2 opens against this document plus the seeded knowledge base (see the research-signals artifact). Do not re-derive Phase 1 — build against the decisions here.

The agent is **domain-agnostic by design** (freedom of content creation, the content hard line aside). The anime/AMV pipeline and the `wardrobe-poc` engagement are future *consumers*, not the design anchor. Phase 1 was anchored on the **platform layer** — pod lifecycle, the ComfyUI backend, the dual cost axes.

This agent is modeled on **voiceover-direction** (cost inversion) and **music-curation** (curated memory), but inherits by reasoning, not template. The three genuine differences (extreme two-axis cost inversion; a running pod costs money during "free" prompt-craft; a node-graph backend + a first-class tutor role) all shaped the decisions below.

---

## Design decisions (central + secondary)

### Central — the turn shape and where the cost axes bite

A generation turn is: **settle offline (free) → spin up → drain a batch in one warm session → spin down.**

- **Phase A is substantial.** Working with the LLM and tutor, you craft settled generation specs and append them to an **editable batch file** (hand-editable, lossless round-trip, per-spec metadata in HTML-comment JSON — the voiceover `.directed.md` pattern extended to hold multiple specs). Each spec carries prompt, negative, model/checkpoint, sampler/steps/CFG, seed strategy, dimensions, LoRA stack, mapped to a ComfyUI workflow. Parameter sweeps are pre-queued variations (multiple specs), not improvised live.
- **Phase B spends.** Opening and holding the warm session is the deliberate paid act; runs inside it are expected iteration.
- **Why session-granularity, not run-granularity** (the voiceover boundary): diffusion iteration needs renders — you often can't settle a prompt without seeing output. And RunPod bills per-second of uptime *and* bills the cold-start (boot + model load), so the discipline is "minimize spin-ups," which is exactly Phase-A-offline → drain-a-batch.
- The editable batch file was chosen over an agent-managed queue chiefly for the **tutor role**: a file you open and read (settings + inline rationale) is a learning surface; a CLI-operated queue hides the specs.

### Q1 — memory types in `visual_generation_memory`

| memory_type | embedded text | role |
|---|---|---|
| `generation` | image/keyframe + caption (multimodal, `voyage-multimodal-3`) | the core record — what was generated, with what, the reaction |
| `technique_lesson` | the statement | curated/confirmed lessons; `scope` = prompt/settings/workflow/model; valence |
| `workflow_template` | a descriptor | reusable parameterized ComfyUI graph + its swap-points |

- `generation` payload: full settings, model/checkpoint, LoRA stack + strengths, `workflow_ref`, seed, dimensions, `asset_path`, per-run cost, `identity_bearing`, reaction, rating, status, chain lineage (`chain_root_id`/`parent_id`), project tag.
- **Not a memory_type — a local registry** (the voice-registry analog): models, checkpoints, LoRAs. Concrete files looked up by name, never semantically searched. Character LoRAs live here; identity opsec attaches at this storage layer.
- **Deferred:** a `reference` memory_type (image+caption, the `sound_reference` analog). Reference-driven direction is the layer voiceover deferred to v2.
- **Reaction vocabulary** (mirrors voiceover's aesthetic/technical split): `loved` / `liked` / `liked_with_changes` / `disliked` (rendered faithfully, not to taste — weighs against the settings) / `render_failed` (artifacts, ignored prompt, bad anatomy — intent didn't render, direction stays open) / `pending`.

### Q2 — relationship to `user_knowledge`

- **Promote `knowledge ingest-docs` to a shared runtime mechanism.** The flow (parse `##`+ headings → candidate → y/n/edit/defer → `bulk_load_verified`) is domain-agnostic; only the `domain` tag and source folder vary. Second consumer has appeared → promote. voiceover-direction is refactored to call the runtime path (behavior-preserving — its CLI is unchanged). The deferred `--decisions`/`--url` refinements then land once for all agents.
- **Domains for this agent:** `comfyui_mechanics` and `runpod_mechanics` (distinct concerns — backend vs. platform).
- **Three-collection retrieval** (mirrors music/voiceover): own `visual_generation_memory` + `user_knowledge` (mechanics, score-boosted) + `tutorial_research` (tutorial-derived diffusion technique). Each leg degrades silently; cold-start usable.
- The line: `user_knowledge` = documented platform/vendor facts; `technique_lesson` = lessons learned by doing; `tutorial_research` = tutorial-derived technique.

### Q3 — the dual budget axis

Confirmed RunPod billing (current as of Phase 1): pods bill **per-second of uptime** (cold start included), a **stopped pod still bills storage** (network volume persists models), and nothing hard-caps per-run spend beyond a default $80/hr global limit.

- **Claude cost → `BudgetEnvelope`** (runtime, unchanged).
- **GPU/pod spend → a separate, agent-local tracker** (different currency: GPU-seconds × rate + storage; nothing caps it underneath). Promote to runtime only if a second GPU-backed agent appears.
- The billed axis is **uptime**, not per-run; per-run minutes are a decomposition for advice. This also confirmed **pod, not serverless** (serverless wraps the native endpoints and cold-starts each request — wrong for a warm session and the tutor role).
- **Measured:** session uptime (dominant), per-run minutes, storage (standing note). **Surfaced:** soft-inform gate at spin-up (estimated session cost from the batch + GPU rate + balance), running total, spin-down nudge on drain. **Recorded:** per-run GPU-seconds + cost as trace events; session totals; per-run cost in the `generation` payload.
- **Enforcement decision: soft-inform only** (advise, never block — you control spend), with an optional per-session ceiling flag available.

### Q4 — pod lifecycle

**Tier-1 advisory** for v1. Start and stop have opposite risk/learning profiles:

- **Start: advisory.** The agent recommends the GPU and tells you to spin up; you operate the console (learning the platform). The agent then talks only to the ComfyUI endpoint you provide — **no RunPod API key in the agent in v1**.
- **Stop: advisory, warnings first-class.** Prompt to stop on batch-drain; surface idle warnings while the pod sits idle. Knowable from the ComfyUI side, no RunPod credential needed.
- **Deferred (Tier-2):** real stop-automation (agent holds a RunPod key, auto-stops on drain/idle). Start stays advisory even then.

### Q5 — the ComfyUI backend interface

- **Mechanics (confirmed current):** workflows in **API format** (node id → `{class_type, inputs}`, as produced by "Export Workflow (API)"); POST `/prompt` → `prompt_id` → `/history/{id}` for outputs → `/view` for assets; `/ws` for live progress; `/object_info` enumerates installed models. Native endpoints are directly reachable on a pod (serverless would wrap them).
- **`workflow_template` = graph + slot map + required models.** The **slot map** (semantic param → `{node_id, input_key}`) is the right primitive: parameterizing is literally writing values into node inputs by id, and positive/negative prompts are distinguishable only by which KSampler input they feed — so a slot map declared once beats re-inferring topology. These slots are the "swap-points" from Q1. `required_models` lets the agent check a batch against the registry and advise before spin-up.
- **Template registration is propose → confirm:** you export a working API-format graph; the agent walks it to propose candidate slots; you confirm/correct once.
- **v1 scope line: consume, don't author.** The agent parameterizes graphs *you* build in ComfyUI; it does not generate graphs from scratch (deferred). Note Flux's parameterization differs from SDXL (CFG=1.0, a separate Flux-guidance slot, no negative prompt) — a per-template slot-map detail.

### Q6 — the tutor role

- **Grounded, not free-floating:** explanations draw on the three-collection retrieval and surface *your own* `technique_lesson`s back to you ("you noted CFG>7 washed skin on this checkpoint"). The tutor improves as memory grows.
- **Three touchpoints:** inline during Phase A spec-drafting (primary, free — same draft call); on-demand `explain <concept>` (deep-dive, a Claude call); at template registration (node-level guidance — where platform-operation tutoring lives, since the agent can't watch the ComfyUI UI).
- **Verbosity is a manual dial** (full/concise/quiet), not auto-detected mastery. Explanations always include retrieved own-lessons; the level only changes how much generic explanation rides along. **Default: concise rationale inline + `explain` for depth.**

### Q7 — stills vs. video

**One path, not two.** Same turn shape, cost model, backend mechanics, memory model, template primitive. Differences are payload/parameterization: video embeds a representative keyframe + caption (asset is the video file); I2V adds an input-image slot + `/upload/image`; an I2V clip's parent can be a prior still (the chain lineage spans types, which unifies them). **v1 is stills-first (Flux)**; video (WAN) is the fast-follow on the same path, built to accept it without rework.

### Q8 — character LoRA handling

- **v1 is LoRA use-only.** Use is free (registry entry + workflow slot). Training (ai-toolkit) is a separate subsystem — dataset prep, training config, a long expensive GPU run, a different turn — **deferred** behind an adoption trigger.
- **Opsec (storage/access layer):** an `identity_bearing` flag on registry entries; identity-bearing LoRAs and the generations using them live in a **secured, isolated path** under `~/agent-data/`, write-guarded against the obsidian vault, `agent-reports`, and any synced location (extends the existing clean-directory-separation rule). Encryption-at-rest is a deferred hardening.
- Distinct from the **content hard line** (no nude generation, no clothed→unclothed of real people), which is enforced at the capability level — not a capability the agent builds.

### Q9 — delegation to tutorial-research

- **Triggers** (mirror music/voiceover): named feature/node with no local high-confidence hit; "why does X work" with no local theory hit.
- **Prompt on a gap, never auto-delegate inline** — a research run is a separate, minutes-long delegation; Phase A stays fast. The agent offers; an explicit `research <topic>` command is the deliberate path. Two-step with cheap fallback (research once, retrieve cheaply after).
- Standard `delegate()` with a child `BudgetEnvelope` (Claude cost only — research touches no GPU). Because the seed corpus exists, triggers fire mostly for `runpod_mechanics` and uncovered technique, not basic ComfyUI mechanics.

### Q10 — CLI surface (sketch)

- **Craft (Phase A, free):** `draft "<intent>" [-o batch.md] [--template <name>]` (naming soft — `craft`/`compose` alternatives)
- **Generate (Phase B):** `generate batch.md (--section <id> | --all) [--endpoint <url>] [-y] [--max-session-cost N]`
- **React:** `report <gen_id> --reaction <X> [--rating] [--notes] [--context]`
- **Inspect:** `review-pending`, `recall "<query>"`, `chain show <root_id>`
- **Direct writes:** `lesson add`, `fact add`
- **Templates:** `workflow register <exported-api.json>`, `workflow list`
- **Models/LoRA registry:** `model sync` (from `/object_info`), `model list` (`identity_bearing` set at register)
- **Knowledge/research/tutor:** `knowledge ingest-docs <folder>`, `research <topic>`, `explain <concept>`

### Q11 — output format

`VisualResult` = asset path(s) + resolved settings recipe (with tutor rationale) + generation record (memory id). **Assets are disk files, not stored in Qdrant** — binary PNG/MP4 referenced by `asset_path`; non-identity in `~/agent-data/visual-generation/assets/`, identity-bearing in the secured isolated path; never the vault. The vector point embeds image/keyframe + caption and references the file by path.

---

## Phase 2 build sequence

Order, grouped for efficiency (no schedule).

**First build session — runtime prerequisite + data foundation:**
1. **agent-runtime:** extract the `knowledge ingest-docs` flow into a shared runtime mechanism; switch voiceover-direction to call it (behavior-preserving); re-run voiceover-direction's suite to confirm no regression.
2. **visual-generation foundation:** the `visual_generation_memory` collection + store wrapper; the three memory types (`generation` multimodal, `technique_lesson`, `workflow_template`); the model/LoRA registry (`model sync`/`list`, `identity_bearing`); the three-collection retrieval composition.

**Then, in order:**
3. **ComfyUI backend + templates** — the client (`/prompt`, `/history`, `/view`, `/object_info`); `workflow register` (propose→confirm) + `workflow list`; one working Flux txt2img template.
4. **The turn** — `draft` (Phase A: editable batch file, lossless round-trip, prompt-on-gap research offer); `generate` (plan → soft-inform GPU gate → submit/poll/fetch → pending generation; advisory spin-up, stop-prompt on drain; agent-local GPU tracker); `report`.
5. **Inspect + writes + tutor** — `review-pending`, `recall`, `chain show`; `lesson add`, `fact add`; `explain`, `research`.

**Deferred (path built to accept them):** video/WAN (fast-follow); LoRA training; RunPod stop-automation (Tier-2); encryption-at-rest for identity artifacts; the `reference` memory type; `ingest-docs --decisions`/`--url` (now shared); graph authoring.

---

## Constraints carried forward

- **Content hard line:** no nude generation, no clothed→unclothed transformation of real people. Capability-level — not built.
- **LoRA-identity opsec:** identity-bearing artifacts isolated + write-guarded against synced/reported locations (Q8).
- **Platform shift from the course:** the course teaches local M1 + Colab; this agent runs ComfyUI on a RunPod pod. ComfyUI *mechanics* transfer; RunPod deployment and headless/API operation are gaps filled by research (see research-signals artifact).

---

## Foundation state to inherit

- **agent-runtime** complete — `MemoryStore` (incl. the multimodal surface: `embed_multimodal`/`voyage-multimodal-3`, `MultimodalInput`, `search_multimodal` — this is the first agent to lean on it), `UserKnowledgeStore`, `BudgetTracker`/`BudgetEnvelope`, delegation, tracing, reporting. The `knowledge ingest-docs` extraction (first build session) lands here.
- **voiceover-direction** complete (145 tests) — the closest precedent (cost inversion, `direct → generate → report`, soft-inform gate, two-budget separation, `ingest-docs`, the local JSON registry pattern). It gains the behavior-preserving ingest-docs refactor in the first session.
- **music-curation** (214 tests), **tutorial-research** (52 tests, the delegation target), **yt-intelligence-pipeline** (45), **concept-script** (45). Standing rules + build methodology in `docs/ai-director-agent-system.md`.

---

## Reference documents

- `docs/ai-director-agent-system.md` — system spec (incl. Visual Generation section), working-relationship rules, build methodology
- `docs/architecture.md` — full agent-stack architecture
- `packages/agent-runtime/README.md` — runtime API (note the multimodal surface)
- `packages/voiceover-direction/README.md` — the primary precedent
- `packages/music-curation/README.md` — curated memory, delegation triggers
- `docs/v2-refinements/v2-refinements-voiceover-direction.md` — `ingest-docs` batch/URL refinements (now shared) and the reference/persona patterns
- `research-signals-visual-generation.md` — the between-phase ingestion list + `tutorial-research` gaps
- The course docs in the project (`comfyui_mechanics` source)
- This handoff
