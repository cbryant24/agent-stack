---
title: Technique Research Agent — Phase 2 Handoff
date: 2026-06-12
type: phase-2-handoff
agent: technique-research
project: agent-stack
status: active
---

# Technique Research Agent — Phase 2 Handoff

Phase 2 (Build to MVP) is complete. The full Mode A turn works end to end and is smoke-verified
on a real goal. This document hands off to **Phase 3 (Refinement)** and carries forward the
post-Phase-2 state plus every captured-but-not-built item. Phase 1 design rationale lives in
`docs/handoffs/technique-research-phase1-handoff.md`; the durable deferred-item record is
`docs/v2-refinements/technique-research-v2-refinements.md`.

## What shipped (MVP)

`packages/technique-research/` — 11 source modules (~1,470 lines) + 8 test files, **40 tests passing**.
The full Mode A turn:

- **`identify`** — toolset read (`user_knowledge` `domain=editing_toolset`, the only source of toolset
  facts, never hardcoded) → ground (yt-dlp metadata + conditional Tavily *reference* search) → identify
  prioritized technique domains (Sonnet, vision-capable; explicit `--scope` authoritative, else inferred)
  → three-collection check with per-leg thresholds + `record_delegation_decision` → interactive gate
  (`-y` / `--plan-only` / per-domain prune / decline-all → curate-from-local) → delegate gaps to
  tutorial-research on child budgets (`max_items` caps delegations, `check_budget()` at the loop top) →
  curate findings grounded in the toolset (with a paid/Studio `upgrade_flag` where relevant) → write
  findings to `technique_research_outputs`, the `TechniqueReport` markdown (`-o`), and the run report.
- **`recall`** — semantic search over own findings.
- **Orchestrator integration** — `technique_research_outputs` as a `search_knowledge` domain;
  `technique_recall` (free) + `technique_identify` (budgeted, the orchestrator's `max_depth=2`
  accommodates the orchestrator → technique-research → tutorial-research chain).

Conventions matched: `src/` layout, per-package `constants.py` (unvalidated thresholds/budgets),
`BudgetTracker` lifecycle (stats read after context exit; no nested `TracePersister`), the `_record_llm`
cost bridge (copied from music-curation), `delegate()` + idempotent handler bootstrap (mirrors
visual-generation), Anthropic client via `get_config()`.

## Smoke test (recorded)

Goal: *"a fast-cut anime music video with speed ramps and chromatic aberration on the beat drops"*,
with image input and the interactive gate exercised (user-run).

- Run `01KTWWDJ6HJ2F5RZE3NXW37Z27` — `completed`, $0.067, 408s, scope `editing`, 5 findings.
- 2 domains delegated to tutorial-research (runs `…EC2K`, `…QJC7`; one returned 0 ingestable videos and
  still produced a sound finding — graceful degrade), 3 resolved locally.
- Verified: TechniqueReport file; **5 points** in `technique_research_outputs` (1024-dim cosine);
  run report in the vault; `recall` retrieves the findings with correct ranking + source refs.
- **Guardrail held:** curation cited Resolve free 20.3.1, the locked RGB-Shift → Fusion workaround, the
  Topaz VFR-as-CFR quirk with the exact `ffmpeg -vsync vfr` insertion point, and surfaced the Studio-only
  Speed Warp upgrade flag — all from `editing_toolset` retrieval, nothing hardcoded.

## Post-MVP polish landed (in Phase 2)

- **Fail-fast `-o` validation.** `-o` previously failed only at the final write (`IsADirectoryError`),
  after identification, the gate, and a paid delegation had already run. Now: the CLI validates the path
  at parse time (creatable parent, not under a file → `click.BadParameter` before any spend), and a
  directory target writes the default filename into it. Covered by `test_cli.py`.
- **Preview gap-label fix.** `--plan-only` reports mislabeled would-delegate gaps as "answered from
  existing knowledge"; now status-accurate via `_GAP_LABELS`.

## Documentation state (current)

Updated to post-Phase-2: `README.md` (agent table, collections table, dir tree, orchestrator row),
`docs/architecture.md` (new `technique-research` section), `docs/ai-director-agent-system.md` (status
flipped to built + Build Order line), `packages/technique-research/README.md` (new). Nothing committed —
the user commits on request.

## Deferred to Phase 3 / V2 (full list in `docs/v2-refinements/technique-research-v2-refinements.md`)

Parked by Phase 1: Mode B footage-based diagnosis (the chain's `text + zero-or-more images + optional
context` input shape is the only provision made); findings carrying reference images (forces a
multimodal embedding-space decision); a `report --reaction` loop; visual-generation querying
`technique_research_outputs` directly; concept-script → technique-research delegation; MCP exposure.

Noticed during the build (non-blocking): **finding→domain source-ref precision** (findings currently
carry the union of all delegation run-ids rather than the specific originating delegation — the most
substantive refinement); per-domain (vs single) curation call; check-threshold tuning from the
`delegation_decision` trace events once runs accumulate; terser `--plan-only` stdout (gap distinction
only in the file); per-domain toolset re-query; adding `technique-research` to
`config._ensure_directories` (cosmetic).

## Phase 3 scope discipline

Phase 3 is smaller-touch: polish a working agent, don't redesign it. Group items by surface area, each
with explicit smoke verification. Anything that lands stays in the docs; anything not done moves to
`docs/v2-refinements/technique-research-v2-refinements.md` with reasoning. The highest-value candidate is the
finding→domain source-ref precision, since it sharpens both the stored findings and the report's
"where to learn more" links.
