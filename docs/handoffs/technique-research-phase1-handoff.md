---
title: Technique Research Agent — Phase 1 Handoff
date: 2026-06-11
type: phase-1-handoff
agent: technique-research
project: agent-stack
status: active
---

# Technique Research Agent — Phase 1 Handoff

Phase 1 (Design and discovery) is complete. All design questions necessary for the build are resolved with documented reasoning. This document hands off to **Phase 2 (Build to MVP)** and carries forward everything Phase 2 needs to begin without re-deriving Phase 1's conclusions.

## What `technique-research` is (resolved)

Originally framed as the "Footage Research Agent," redefined: the director sources clips himself, so this is not clip discovery — it is **technique discovery**. "I want to make a video like X — what techniques are involved?"

**The central design question (confirmed):** what does technique-research distinctly own and decide that tutorial-research doesn't — given that tutorial-research already discovers, ingests, and synthesizes? The settled answer, in three parts:

- **(a) The identification layer — "goal → prioritized technique domains."** Tutorial-research takes a topic as *given* and gathers; it never decides which topics matter. Technique-research owns exactly that decision: given a creative goal (optionally an image of the look, optionally a reference URL), it reasons to a prioritized set of technique domains, each with why-it-matters reasoning.
- **(b) The control flow — identify → check existing knowledge → delegate → curate.** The economizing step is **check**: before delegating a domain, it queries what's already known and only delegates genuine gaps. This agent is the heaviest exerciser of cross-agent delegation in the system; that is its plumbing identity.
- **(c) The curated layer — relevance decisions, not material.** The `tutorial_research` collection holds *material*. The TechniqueReport holds *decisions about relevance*: which techniques this goal needs, why, in what priority, how to apply them, and consumer-directed signals. Consumers act on the curation instead of re-deriving it.

**The redundancy test (the anti-redundancy boundary, in one line):** tutorial-research answers "gather and synthesize material on topic T"; technique-research answers "which T's does this goal need, what do we already know, and here's the curated result." It adds the deciding and the curating, and duplicates none of the gathering. No tutorial discovery, no ingestion, no yt-pipeline calls happen in this agent — ever. The moment material needs gathering, that's a delegation.

**The Tavily boundary:** both agents use Tavily, but for different purposes. Tutorial-research searches for *tutorials to ingest*. Technique-research searches to *understand the reference* — what "videos like X" actually are, exemplars, commentary. Reference discovery, never tutorial discovery.

## Mode A / Mode B scoping (resolved)

- **Mode A (reference-based) is V1.** Claude reasoning + conditional Tavily reference discovery, with two *optional* inputs: a reference image (the technique may just be a look — Claude vision analyzes it directly as identification context) and a video URL accompanying it (yt-dlp metadata/description as additional context — cheap, no frame extraction).
- **Mode B (footage-based diagnosis) is V2, parked.** A YouTube URL + start/stop timestamps, or a local video file → ffmpeg interval frame extraction → multi-frame Claude-vision technique diagnosis → search/match on the diagnosis. All primitives exist in the stack (ffmpeg in yt-intelligence-pipeline, multimodal throughout); nothing needs proving now.
- **The one V1 provision for Mode B:** the identification chain's input model is designed as **"text + zero-or-more images + optional context"** from the start. Mode A's optional image already makes the chain multimodal (Claude vision — analysis in the prompt, no embedding involved); Mode B later becomes *more frames into the same chain* plus an extraction front-end and interval logic — an extension, not a redesign. A frame *sequence* additionally lets Claude diagnose techniques that only exist across time (cut rhythm, speed ramps, a transition mid-execution).

The two multimodal mechanisms must not be conflated: **Claude vision** (images in the prompt, analysis) is what the identification chain uses; **Voyage embeddings** (storage/retrieval — `voyage-3-large` text vs. `voyage-multimodal-3` image+caption, incompatible 1024-dim spaces) matters only for the memory model below.

## Memory model (resolved): owns `technique_research_outputs`

The test that made concept-script stateless was "is there a learning mechanism that earns a collection?" Technique-research **passes** it, and not via a reaction loop: its own **check** step is the retrieval consumer. The second time a similar goal arrives, check retrieves prior curated findings before re-identifying or re-delegating — the collection is what makes run N+1 cheaper than run N. The Orchestrator also gets it for free as a `search_knowledge` domain (a registry entry).

- **Stored unit: the per-technique finding, not the report.** A report is a project-scoped bundle; what's reusable across projects is the individual finding (technique → description, why it matters, application notes, toolset fit, source refs back to tutorial-research runs, the goal/domain context it was curated for). Retrieval wants findings; the report file is the per-project assembly of them.
- **Embedding space: text-only, `voyage-3-large`.** Even when images inform identification, the *finding* is text — images are chain inputs, not memory. Same space as `tutorial_research`/`user_knowledge`; trivial orchestrator integration; avoids the cross-space mismatch class the diagnostics probe exists to catch. A finding carrying its reference image is a deliberate revisit, not a default.
- **Writes: the agent writes findings as run output under its own ownership** (the owner-writes rule) — no propose/confirm gate, because curation *is* the agent's job here; the director's edit surface is the report file. `--plan-only` runs write nothing.
- **Dual output** mirrors tutorial-research's pattern: the markdown TechniqueReport is the consumer-facing artifact; the collection points are the canonical accumulating layer; the standard run report goes to the agent-reports vault.

Exact payload schema is Phase 2 work (no premature schemas); the decisions above — unit, space, write path — are what Phase 2 needs.

## Technique identification (resolved): inputs and mechanics

**Inputs (v1):**

- Required: the creative goal as text.
- Optional: video type/domain (AMV, game review, travel — inferable when omitted); zero-or-more reference images; a reference video URL (yt-dlp metadata/description only); `--ref` to a prior TechniqueReport ("like that project, but…").
- Optional **scope hint** — `editing | generation | both`. Claude infers from the goal by default ("a video like X" → editing; "images like X" → generation, i.e. ComfyUI/Flux/WAN/LoRA territory); the explicit flag prevents misrouting when ambiguous. Scope determines the report's primary consumer.
- Toolset context is **not** a per-run input: the chain reads `domain=editing_toolset` from `user_knowledge` automatically.

**Identify — a two-stage reasoning step:**

1. **Ground the reference.** If a URL is supplied, fetch its metadata. If the reference is named but under-specified ("like Xenoz edits"), Claude flags it and *only then* Tavily runs reference discovery — conditional, Claude-triggered, not unconditional, so a well-specified goal costs zero searches.
2. **Identification call.** Claude (vision-capable) takes goal + images + grounded context + retrieved prior findings and emits the prioritized technique domains with rationale.

**Check-before-delegate:** per identified domain, query `technique_research_outputs` (own prior findings), `tutorial_research`, and `user_knowledge`; a max-score threshold per collection decides `local` vs `delegate`; constants in `constants.py` as unvalidated starting values; every decision recorded via `record_delegation_decision` — the music-curation pattern verbatim, no new mechanism.

**The identify→delegate gate (resolved: the gate exists).** Identification is cheap; delegation is where budget goes (each delegation is a tutorial-research run). The director prunes the technique list before gathering spends — the same principle as tutorial-research's plan-only and the standing "approving candidate selections when budget-tight" director task.

## The TechniqueReport and its consumers (resolved)

**Form:** an editable markdown file the director owns, written to a user path (`-o`), plus the collection points, plus the standard run report. Contents at decision level: the goal and grounded reference summary; the prioritized techniques — each with description, why-it-matters for *this* goal, how-to-apply grounded in the gathered material and the director's toolset (with a paid/Studio **upgrade flag** where a technique is materially faster or only possible in a paid tool — a field surfaced only when relevant, never a sales pitch), and where-to-learn-more linking back to tutorial-research run reports and sources; the gaps that triggered delegations and their outcomes; consumer-directed sections per scope ("for the brief" when editing-scoped, "for generation" when generation-scoped).

**Consumption is loose-coupled — two channels, both already wired:**

1. **The knowledge channel (automatic).** Material gathered by technique-research's delegations lands in `tutorial_research` — which visual-generation's three-leg retrieval *already queries* on every `draft`, `explain`, and `recall`. When the goal is "images like X" and technique-research delegates gathering on Flux style-prompting or WAN I2V, visual-generation gets smarter with zero integration work. The same holds for any consumer of `tutorial_research`.
2. **The artifact channel (director-mediated).** The report feeds concept-script as seed material (`draft --seeds` already accepts arbitrary markdown — no new contract; the director curates what carries forward). For visual-generation, the report's generation section supplies the intent language and technique names to hand to `visual-generation draft`. For edit-brief (unbuilt): no contract designed; well-structured findings (technique → where it applies) are all the future-proofing v1 does.

The generation-technique relationship, resolved in one line: **technique-research identifies the generation-technique domains, tutorial-research gathers them, the material lands where visual-generation already looks, and the report tells the director what to ask visual-generation for.** No agent gained a dependency.

## Cross-agent dynamics (resolved)

- Delegation-map edges unchanged (`→ Tutorial Research` delegation; `informs → Concept & Script`; `informs → Visual Generation`; `signals → Edit Brief` when built) — but the *mechanism* is now named: the knowledge channel vs. the artifact channel above.
- **Orchestrator wrapping:** the wrapping convention excludes ops that spend *external* money (GPU, ElevenLabs characters) — technique-research has none, and `research_tutorials` is the precedent for wrapping a budgeted-spend op. Both ops get wrapped: **`technique_recall`** (free, embedding-only) and **`technique_identify`** (the full run, child-budgeted). Orchestrator's `max_depth=2` accommodates orchestrator → technique-research → tutorial-research exactly. Plus the `search_knowledge` registry entry for `technique_research_outputs`.

## CLI surface and budget model (resolved)

```bash
technique-research identify "<goal>" [--image <path>]... [--url <video-url>] [--ref <report.md>] \
    [--scope editing|generation|both] [-o report.md] [--plan-only] [--max-cost N] [-y]
technique-research recall "<query>" [--limit N]
```

- **Interactive confirm by default** at the identify→delegate gate (the visual-generation gate pattern): after identification the director sees the technique list and the delegation plan with estimated cost, and prunes per-domain. `-y` skips; `--plan-only` stops at the gate entirely (no delegation, no collection writes — preview only).
- **Declining all delegations at the gate is not an abort** — the run proceeds to curate from existing knowledge only, giving a cheap "what do we already know about this" mode without a separate flag.
- No `report --reaction` command in v1 — findings have no reaction loop (revisit list).
- Library API mirrors the stack: `identify` / `identify_sync` → `TechniqueResult`.

**Budget:** one per-run `BudgetEnvelope`; each approved delegation derives a child via the standard `delegate()` path. Identification is cheap (one or two Sonnet calls); delegations dominate, and the gate is the real spend control. Starting values, unvalidated:

```
DEFAULT_BUDGET: max_items=5, max_depth=1, max_cost_usd=5.00, max_wall_time_sec=2700
```

`max_items` caps techniques gathered (delegations); `max_depth=1` permits exactly the one hop to tutorial-research (which delegates no further); cost and wall time sized for identification plus ~2 delegations at tutorial-research's own defaults ($2.00 / 900s each).

## First build session scope (concrete)

The complete Mode A turn, nothing more — this *is* the MVP, same bar as the other agents' Phase 2:

1. **Foundation.** Package scaffold; data models (`TechniqueResult`, the finding payload, report serialization); runtime wiring (`BudgetEnvelope`, tracing, reporting, Claude client via `get_config()`).
2. **Identification chain.** Text + zero-or-more images + optional yt-dlp URL context + `--ref`; scope inference with override; conditional Tavily reference grounding; `editing_toolset` read from `user_knowledge`.
3. **Check + gate + delegate.** Three-collection check with thresholds and `record_delegation_decision`; the interactive gate (`--plan-only` / `-y` / per-domain pruning / decline-all → curate-from-local); tutorial-research delegation on child budgets.
4. **Curation + outputs.** Findings → `technique_research_outputs`; the TechniqueReport file (`-o`); standard run report.
5. **`recall`** over own findings.
6. **Orchestrator integration.** `technique_recall` + `technique_identify` sub-agent tools; `search_knowledge` registry entry.
7. **Tests throughout**; end-to-end smoke test on a real goal.

## Research signals (between-phase; nothing gathered in Phase 1)

1. **Hand-author a short toolset doc** — the tools the director owns and uses (DaVinci Resolve free, ffmpeg, mpv; versions, constraints) → `ingest_docs` into `user_knowledge`, `domain=editing_toolset`. This is the cold-start gap: the identification chain reads this domain on every run, and it is currently empty.
2. **Tool-landscape research** — tutorial-research run(s) on the current editing-tool landscape and the DaVinci Resolve free-vs-Studio delta; distillations land in `editing_toolset` / `tutorial_research`. (Chosen deliberately over answering in-chat: the findings become durable, queryable material, and answering "what would Studio buy me" is exactly the kind of question this agent and its delegate exist for.)

No other cold-start gap: technique knowledge itself is gathered at runtime by design — that is the agent's job, not a prerequisite.

## Revisit list (parked, not worked)

- **Mode B footage-based diagnosis** (V2) — the chain's multimodal input shape is the only V1 provision made.
- visual-generation retrieval querying `technique_research_outputs` directly (a change to a built agent; not needed for the v1 loop).
- A reaction loop on findings (`report --reaction`).
- Findings carrying reference images (multimodal storage — would force an embedding-space decision).
- concept-script → technique-research delegation (already on concept-script's v2 list).
- MCP exposure (system-wide deferral).

## Working-relationship rules

Unchanged and in force — see the "Working-relationship rules" section of `ai-director-agent-system.md` (single-version-of-inputs, treat as senior programmer, terminal-first, decisions-with-reasoning, no timelines). Not restated here.

## Phase 2 scope discipline and end condition

**Scope:** build to MVP per the build order above. Resist adjacent additions ("while we're at it…"); they go to the deferred list, not into Phase 2. Phase 2 opens with the handoff-verification turn: the director re-reads this document fresh and confirms or flags drift (including anything learned during the between-phase `editing_toolset` ingestion) before any build prompt is sent.

**End condition:** `identify` runs the full Mode A turn on a real goal — grounding, identification, check, gate, delegation, curation — producing a TechniqueReport file, `technique_research_outputs` points, and a run report; `recall` retrieves findings; the orchestrator tools work; the test suite passes; a successful end-to-end smoke test is recorded. At that point Phase 2 is MVP-complete and deferred items are written to `docs/v2-refinements/technique-research-v2-refinements.md`.
