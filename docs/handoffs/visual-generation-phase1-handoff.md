# Handoff: visual-generation agent — Phase 1

**Status:** Not yet started. Phase 1 (design and discovery), no code.
**Predecessor work:** concept-script (complete). voiceover-direction (complete). music-curation (complete). tutorial-research (complete). yt-intelligence-pipeline (complete). agent-runtime foundation (complete).
**Date:** 2026-06-08

---

## Read this first

We're at the beginning of a new agent build. The next chat will execute **Phase 1** of the `visual-generation` agent — design and discovery. The phased-build methodology that scopes this work is documented in `docs/ai-director-agent-system.md` under the build-methodology section. Read it before proceeding; this handoff is specific to visual-generation but inherits the general framework from there.

The most important constraint for Phase 1 is the same one that made the music-curation and voiceover-direction builds work:

**Don't write any code. Start by working through the design questions as a real design conversation.** No premature schemas, no premature architecture, no jumping to a build prompt. The shape of this agent is genuinely undetermined right now — its turn shape, its memory model, its workflow primitives, its CLI surface, its relationship to the GPU/pod cost layer, and even what "good output" looks like are all open.

What worked for the prior builds and should work here:

- One central design question opened first, fully explored, before secondary questions
- Each decision recorded with its reasoning, not just its conclusion
- No batteries of small clarifying questions — one targeted question at a time when a genuine fork emerges
- Explicit recognition of when the user is the only one who can answer something vs. when the design has a defensible answer Claude should propose

This agent is modeled on **voiceover-direction** (the cost inversion) and **music-curation** (curated memory). As with those builds, inherit patterns by reasoning, not by template — and note three ways this agent is genuinely different, so wholesale transfer will mislead:

1. **The cost inversion is more extreme and two-axis.** Direction/prompt-craft is free LLM iteration, but the scarce axes are *GPU/pod uptime* (per-hour) and *generation runs* (GPU-minutes per image, far more per video clip) — and these are a separate budget axis from Claude.
2. **A running pod costs money during "free" prompt-craft.** Unlike voiceover-direction, where direction is genuinely free because it's pure LLM with no running infrastructure, here the GPU pod burns money whenever it's up — including while the user iterates prompts. The "direction is free" claim has a pod-lifecycle asterisk that voiceover-direction did not.
3. **It drives a node-graph backend and carries a tutor role.** ComfyUI (a workflow-graph engine driven via its API) and a first-class platform-tutor responsibility are both new to this stack.

## Phase 1 scope and end condition

Per the build-methodology section, Phase 1's scope is: architecture, technology/platform confirmation, memory model, workflow shape, CLI surface, the GPU/pod budget-axis design, the pod-lifecycle and tutor-role mechanics, the RunPod advisory-vs-automation decision, and any other design questions specific to this agent. No code is written.

Phase 1 ends when:

1. All design questions are resolved with documented reasoning
2. Phase 2's first build session has a concrete scope proposal
3. All research signals identified (gaps in `user_knowledge` / `tutorial_research`) have been produced — as Claude Code prompts for `tutorial-research` invocations and/or a list of the course documents/URLs to ingest manually
4. The Phase 2 handoff document is drafted

The user then performs the between-phase research gathering as their own activity. Phase 2 opens with a fresh chat against a knowledge base that already has the identified gaps closed.

## What's already known about this agent

The agent is specified in `docs/ai-director-agent-system.md` under "Visual Generation Agent — `visual-generation`." Read it. Anchored there:

- **Purpose — three intertwined roles.** *Prompt-craft* (creative intent → effective prompts/settings), *platform tutor* (plain-language, step-by-step explanation of settings — CFG, steps, sampler, the WAN 2.2 high-noise/low-noise split, shift, LoRA strength — and what to do next on the platform), and *generation + iteration* (drive the backend via API, capture results, curate toward target). The tutor role is a genuine responsibility, not a side note: the director is an experienced programmer but a novice in *this* domain who learns by doing.
- **Two consuming projects, baked into neither.** The anime/AMV creative pipeline (character imagery, thumbnails) and a separate adult-content contractor engagement (`wardrobe-poc`: clothed wardrobe and scene variation on a consenting subject, the subject being the user himself). Standalone, domain-agnostic — same pattern as music-curation and voiceover-direction.
- **Platform (starting point — Phase 1 confirms).** RunPod for pay-per-hour GPU (chosen for a permissive legal-adult-content policy and clean isolation from personal identity; Colab ruled out). ComfyUI as the backend, driven via its `/prompt` and `/view` API. Starting-point models: Flux.1 dev (stills), WAN 2.2 T2V/I2V/VACE (video), SDXL checkpoints, character LoRAs (trained via ai-toolkit) for identity lock. Seeds, not commitments.
- **The central cost inversion (dual budget axes).** Per-run Claude cost stays in `BudgetEnvelope`; GPU/pod spend is tracked and advised on a separate axis; pod start/stop discipline is part of what the agent tracks.
- **Memory model.** Owns a `visual_generation_memory` Qdrant collection: generation history (prompt + settings + workflow → result → reaction), settings/technique lessons, reusable ComfyUI workflow templates, reference notes. Curated, not auto-harvested. Platform-mechanics facts live in `user_knowledge` (`domain=comfyui_mechanics`, `domain=runpod_mechanics`). **This is the first agent whose own generation memory leans on the `voyage-multimodal-3` image+caption embedding** — its outputs are images.
- **Scope hard line.** The platform permits legal adult content, which the agent supports where that is the project. The hard line carried from `wardrobe-poc`: clothing/scene variation and creative generation only — **nude generation or clothed-to-unclothed transformation of real people is out of scope and is not a capability the agent builds.** Operational security for identity-bearing artifacts (character LoRAs encode identity) lives at the storage/access layer, not the model layer.
- **Cross-agent dynamics.** Concept & Script / Technique Research inform *what* to generate; the agent delegates to Tutorial Research for ComfyUI/Flux/WAN/LoRA technique gaps; it feeds generated stills/clips to Edit Brief as assets.

The system spec deliberately leaves the rest undetermined.

## What's NOT known (and should not be assumed)

- **Don't assume voiceover-direction's lifecycle transfers wholesale.** The `direct → generate → report` split may map (direction free, generation a deliberate paid commitment), but generation here also has a *pod lifecycle* (start pod → generate → stop pod) that voiceover-direction had no equivalent of.
- **Don't assume the memory types from voiceover-direction / music-curation transfer.** Multimodal image+caption generation memory is new; reusable ComfyUI workflow graphs as a memory type are new; what warrants being a `memory_type` vs. payload is open. The reaction vocabulary for image/video output is open (the music `loved/liked/prompt_failed` and VO `disliked/render_failed` distinctions may or may not map).
- **Platform and models are seeds.** Phase 1 confirms RunPod/ComfyUI/Flux/WAN/SDXL/LoRA and surfaces the fuller model/tool set — that surfacing is part of building the agent well.
- **The node-graph backend is a novel sub-problem.** How the agent represents, templates, and parameterizes ComfyUI workflow JSON is unlike anything the prior agents drove.
- **The tutor role's mechanics are open** — how plain-language guidance is produced and when it surfaces.
- **RunPod API: advisory vs. automation is an explicit Phase-1 decision** — Tier-1 advisory (tell the user to start/stop the pod) vs. actual pod-lifecycle automation.

## Inputs to the build

### Knowledge seed corpus exists (unlike voiceover-direction's cold start)

Voiceover-direction started cold on domain knowledge. Visual-generation does not: the Stable Diffusion / ComfyUI / WAN / Veo course documents already in the user's course project are a named `user_knowledge` ingestion source (`comfyui_mechanics`, `runpod_mechanics`). So the between-phase activity here is closer to "ingest what's already gathered" than "go gather." There is, however, no *generation-memory* seed — no prior generation records exist, so generation memory accumulates from first use, the way voiceover-direction's takes did.

### Domain context

Diffusion image/video generation for two projects (anime/AMV imagery + the `wardrobe-poc` engagement). Its own domain and its own memory — no expected overlap with the music or voiceover collections.

### Novice-by-doing in this domain

The user is an experienced programmer but new to diffusion/ComfyUI, and learns by doing rather than by reading concepts — which is exactly why generic ComfyUI/Udemy tutorials did not work for him, and why the tutor role is a first-class responsibility rather than a nicety. Design the first-use experience so the agent is useful and instructive from the first generation.

## The central design question

Open this first, fully explore it, before anything else:

**What does a generation "turn" look like once the GPU pod is in the loop — and where do the two cost axes actually bite?**

Voiceover-direction's turn was: direct freely (free) → spend characters on generation as a deliberate commitment → listen → report. The cost inversion was clean because direction touched no running infrastructure.

Here it is not clean, and that is the crux. Possibilities, none committed:

- Is prompt-craft truly free, or is it free *only while the pod is down* — making "spin the pod up" itself the deliberate-commitment boundary, with all iteration before it being LLM-only?
- Is a turn: settle prompt + settings offline (free) → start pod → batch-generate → stop pod → react? Or does iteration happen with the pod warm, accepting the uptime cost as the price of a tight loop?
- What does the agent track and advise on across that lifecycle — pod uptime, per-run GPU-minutes, cumulative session spend?
- What counts as a "good" output the user wants to remember — a settings recipe? A workflow template? A generation record with its image? A technique lesson?
- How does the still-vs-video split (Flux vs. WAN, and video far more GPU-costly) change the turn shape?

The answer to this question drives the budget-axis design, the CLI surface, and the memory model — so it comes first.

## Secondary questions (do not open until the central one is settled)

Work through these in order, each building on the previous:

1. **Memory types in `visual_generation_memory`.** Evaluate, don't assume: generation records (multimodal image+caption embedded), reusable ComfyUI workflow templates, settings/technique lessons, reference notes, character-LoRA references. Which warrant a `memory_type`, which are payload, which combine. Plus the reaction vocabulary for visual output.
2. **Relationship to `user_knowledge`.** `comfyui_mechanics` / `runpod_mechanics` facts seeded from the existing course docs. Decide whether to reuse voiceover-direction's built `knowledge ingest-docs` path (and whether to promote it to a shared runtime mechanism) or build the equivalent here.
3. **The dual budget axis as design driver.** Claude cost in `BudgetEnvelope`; GPU/pod spend tracked and advised separately. How is pod/GPU spend measured (per-hour uptime + per-run minutes), surfaced before a run (a soft-inform gate, like voiceover-direction's character gate), and recorded (trace events? a separate tracker)?
4. **Pod lifecycle management.** Advisory (Tier-1: surface start/stop guidance) vs. automation (RunPod API drives the pod). The spec flags this explicitly. Cost discipline lives here.
5. **The ComfyUI backend interface.** `/prompt` + `/view`, with workflow JSON as the unit. How does the agent represent, template, and parameterize graphs? This is the hardest novel sub-problem — none of the prior agents drove a node-graph backend.
6. **The tutor role mechanics.** How plain-language explanations of settings are produced, and when they surface (always, on demand, or when the user operates the platform directly).
7. **Stills vs. video.** Whether Flux-stills and WAN-video share one turn/workflow/memory shape or diverge enough to be separate paths (video's GPU cost is much higher).
8. **Character LoRA handling.** Is LoRA *training* (ai-toolkit) in v1 scope, or only LoRA *use*? The identity-bearing opsec (LoRAs preserve identity through transformations) routes to the storage/access layer.
9. **Delegation to tutorial-research.** When the agent delegates for ComfyUI/Flux/WAN/LoRA technique gaps; the trigger pattern (mirror music-curation/voiceover-direction: named feature with no local high-confidence hit, "why does X work" with no local theory hit) adapted to this domain.
10. **CLI subcommand surface.** Falls out of the workflow shape — don't pre-list.
11. **Output format.** A structured `VisualResult` analog: generated asset files (binary, not text), the settings recipe (each choice explained for the tutor role), and the generation record. How assets are referenced/stored is open.

## Research signals expected from Phase 1

Likely, but partially pre-seeded. Anticipated categories (Phase 1 confirms and refines):

- **ComfyUI / RunPod / Flux / WAN mechanics** — primarily from the existing course documents via a doc-ingestion path (`comfyui_mechanics`, `runpod_mechanics`), supplemented by `tutorial-research` delegations for gaps the course docs don't cover.
- **Diffusion / generation technique** — prompt structure, sampler/CFG/steps tradeoffs, LoRA stacking, ControlNet/IP-Adapter, the WAN high/low-noise workflow — likely YouTube-tutorial ingestion via `tutorial-research`.

Produce these as concrete, actionable artifacts: a Claude Code prompt running `tutorial-research <topic>` per identified topic, and a list of the specific course documents (already in the project) to ingest via the docs path. Because voiceover-direction already built `knowledge ingest-docs` → `user_knowledge`, Phase 1 should decide whether visual-generation reuses that mechanism or whether it gets promoted to a shared runtime path before Phase 2.

If Phase 1 concludes no research signals are needed (unlikely), it states so explicitly in the Phase 2 handoff and Phase 2 begins immediately.

## What Phase 1 should NOT do

- Propose a memory schema before the central turn/pod-lifecycle question is settled
- Lift voiceover-direction / music-curation CLI subcommands or memory types without justifying each — the backend and cost model differ
- Write code
- Assume the workflow shape transfers from voiceover-direction (pod lifecycle and a node-graph backend are both new)
- Commit to RunPod / ComfyUI / Flux / WAN as final without confirming them
- Begin actual research ingestion (that's the between-phase activity)
- Treat the user as a diffusion expert (he is a deliberate novice in this domain) — but do not treat him as a novice programmer
- Design past the content hard line: no nude generation and no clothed-to-unclothed transformation of real people — that is out of scope and not a capability the agent builds

## What Phase 1 SHOULD produce, in order

1. A worked design conversation on the central question (turn shape + pod lifecycle + where the two cost axes bite + what memory persists), ending with a stated answer the user has confirmed
2. A worked design conversation on each secondary question, in order, each building on the previous
3. A concrete proposal for Phase 2's first build session — what lands first, its dependencies, what's deferred
4. Research signals (Claude Code prompts for `tutorial-research` and/or the list of course docs to ingest) as downloadable artifacts
5. A Phase 2 handoff document — downloadable — containing everything Phase 2 needs without re-deriving Phase 1: the design decisions reached, the memory model, the workflow shape, the CLI surface (sketch level), the dual-budget design, the pod-lifecycle decision, the Phase 2 build sequence, and constraints carried forward (the content hard line and the LoRA-identity opsec among them)

## Foundation state to inherit

Phase 1 begins on top of:

- **agent-runtime** complete (168 tests). Provides `MemoryStore` — including the multimodal surface directly relevant here (`embed_multimodal` / `voyage-multimodal-3`, `MultimodalInput` for text+image, `search_multimodal`) since this is the first agent to lean on image+caption embeddings — plus `UserKnowledgeStore`, `BudgetTracker` / `BudgetEnvelope`, delegation primitives, tracing, and reporting. Public API in `packages/agent-runtime/README.md`.
- **voiceover-direction** complete (145 tests) — the closest precedent: the cost inversion, the `direct → generate → report` split, the soft-inform cost gate, the two-budget separation (Claude in the envelope, vendor budget orthogonal and never cached), `knowledge ingest-docs`, and the local JSON voice registry (a possible analog for a local model/checkpoint/LoRA registry). Reference, do not copy.
- **music-curation** complete (214 tests) — curated-write discipline, the four-memory-type pattern, `seed ingest`, delegation triggers. Reference, do not copy.
- **tutorial-research** complete (52 tests) — the delegation target and the between-phase ingestion arm.
- **yt-intelligence-pipeline** complete (45 tests). **concept-script** complete (45 tests).
- **Standing rules** and the **build methodology** in `docs/ai-director-agent-system.md`. These apply to Phase 1.

Full workspace: 669 tests across six packages.

## Reference documents

Load these as context at the start of Phase 1:

- `docs/ai-director-agent-system.md` — system spec, including the Visual Generation section, the working-relationship rules, and the build methodology
- `docs/architecture.md` — full agent-stack architecture
- `packages/agent-runtime/README.md` — what the runtime provides (note the multimodal embedding surface)
- `packages/voiceover-direction/README.md` — the primary precedent (cost inversion, dual budgets, lifecycle, `ingest-docs`, registry)
- `packages/music-curation/README.md` — curated memory, seed ingest, delegation triggers
- `docs/v2-refinements/voiceover-direction-v2-refinements.md` — the `ingest-docs` batch/URL refinements and the reference/persona/chat-mode patterns that may apply analogously
- The Stable Diffusion / ComfyUI / WAN / Veo course documents (already in the project) — the `user_knowledge` ingestion source
- This handoff document

## One open question for the user before opening Phase 1's design conversation

Answer this in the first message to the Phase 1 chat, because it shapes the very first turn of the central design conversation:

**Which project anchors Phase 1 — the anime/AMV imagery pipeline, or the `wardrobe-poc` engagement — and is there a specific first generation target right now?**

The two differ in what "good output" means, in model/workflow emphasis (AMV: character imagery, thumbnails, possibly video; `wardrobe-poc`: character-LoRA identity-lock plus clothed wardrobe/scene variation), and in cost profile (video generation is far more GPU-costly than stills). Grounding Phase 1 in one concrete project — ideally a real first generation the user wants to produce — makes the design questions concrete instead of abstract. Either is a valid starting point; both shape the conversation differently.
