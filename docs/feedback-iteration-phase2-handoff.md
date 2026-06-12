---
title: Feedback & Iteration Agent — Phase 2 Handoff
date: 2026-06-12
type: phase-2-handoff
agent: feedback-iteration
project: agent-stack
status: complete
---

# Feedback & Iteration Agent — Phase 2 Handoff

**Phase 2 (Build to MVP) is complete.** The `revise` turn runs end to end against
the real `script-draft.edit-brief.md`, the time-shift engine and brief parser are
fully unit-tested, and the orchestrator now wraps both ops. Build Session 1 built
the agent; Build Session 2 wrapped it. Both sessions' records are below.

## What shipped

`packages/feedback-iteration/` — imports only `agent-runtime`; parses the
edit-brief artifact as a foreign artifact by its anchors (no `edit-brief` import).

CLI: `feedback-iteration revise BRIEF.md "feedback" [--feedback FILE] [--max-cost N] [--dry-run]`

Modules (mirroring edit-brief's roles):
- **`parser.py`** — foreign-artifact reader → `ParsedBrief` with char-offset
  `Span`s for every patchable surface (frontmatter version, timeline cells,
  section anchors/headings/timespans, checkbox steps with checked state,
  notations, the version log). Independent `_slugify` copy. No LLM.
- **`time_engine.py`** — PURE, fully unit-tested. `measure_gaps`,
  `adjust_section_duration`, `set_section_duration`, `shift_section` → `ChangeMap`
  (new rows + per-section resized/shifted/unchanged diff + the deduped boundary
  substitutions). The LLM never produces a number.
- **`patcher.py`** — pure string-splice `apply_patches` (right-to-left, disjoint
  spans) + op builders + bounded prose retiming (`substitute_prose_boundaries`,
  `retime_text`) value-scoped to changed boundary tokens.
- **`versioning.py`** — `snapshot` (verbatim copy to `versions/<stem>.v{N}.md`
  before any patch), `bump_version_patch`, `version_log_patch`, `build_log_entry`.
- **`chains.py`** — one Sonnet mapping/diagnosis call; JSON parse + retry-once +
  the `_record_llm`→BudgetTracker bridge. The time-shift schema carries `op` +
  `magnitude_sec` + `magnitude_source_quote` — **no resulting-timestamp field**.
- **`retrieval.py`** — feedback-driven grounding: `editing_toolset` always,
  `technique_research_outputs`, `tutorial_research`, `user_knowledge` (1.25×).
- **`lessons.py`** — propose-only `editing_preference` lessons with provenance.
- **`agent.py`** / **`cli.py`** — `revise`/`revise_sync` control flow, the
  free `--dry-run`, BudgetTracker envelope, run-report finalize.

## Design decisions made this session

1. **Downstream prose retiming: bounded substitution now** (user-confirmed). The
   engine emits the exact changed boundary values; the patcher substitutes only
   those literal `N.NNNs` tokens in shifted sections' steps *and notations*. The
   `0.500s` gap token and unchanged `duration =` tokens are excluded. A resized
   section also retimes its own changed duration token.
2. **Numberless timing requests → unresolved** (user-confirmed). The stated
   amount must be a number traceable verbatim to the feedback (`magnitude_source_quote`
   must contain a digit and be a substring of the item); otherwise the item is
   left unapplied with a clarifying note. The LLM never invents the magnitude.
3. **Check-state policy.** A substantive LLM rewrite of a checked step unchecks it
   and names it invalidated in the version log; a mechanical downstream cascade
   preserves check state.
4. **Lessons propose-only.** v1 has no interactive mode; auto-confirm would write
   durable retrieval-affecting bias from one unreviewed turn. Drafts are surfaced
   by id; the director gates `confirm` out of band.
5. **Always one version bump per real run** — snapshot + frontmatter bump +
   version-log entry, even when only unresolved items exist (the trail is the
   point). `--dry-run` writes nothing and spends nothing.

## Verification

- `uv run pytest packages/feedback-iteration/tests/` → **41 passed, 1 skipped**
  (the opt-in smoke). `uv run ruff check packages/feedback-iteration/` clean.
  - Pure unit tests: time engine (cascade, gap preservation, boundary_subs
    excludes the gap, rounding, error cases) and parser (round-trips the real
    artifact: 7 anchors, span slices, checked state, frontmatter version).
  - Patcher: order-independent splice, overlap rejection, bounded prose
    substitution leaves the gap + unchanged durations alone, checkbox 3-char flip.
  - Versioning: verbatim snapshot, version-only bump, log created/extended.
  - Chains (mocked LLM): message carries sections+timing+feedback; time_shift
    parses with quote and no timestamp field; retry-once; fenced JSON tolerated.
  - Agent: dry-run echoes + writes nothing + no `versions/`; full run patches in
    place, snapshots v1, bumps to v2, unchecks+invalidates a checked rewritten
    step, retimes a stale rewrite token through the cascade, surfaces the
    unmappable item, proposes (not confirms) a lesson; numberless timing demotes
    to unresolved.
- **Free op (live CLI):** `revise script-draft.edit-brief.md "…" --dry-run`
  printed the parse/validate/echo + snapshot plan, wrote nothing, spent nothing.
- **Smoke (recorded, live):** `FEEDBACK_ITERATION_SMOKE=1 uv run pytest
  packages/feedback-iteration/tests/test_smoke_fixture.py -s` → **passed**,
  ~$0.039, 25s. Feedback: tighten *The calm underneath* by 2s (middle-section
  cascade) · the close fade should be 2s · "calm sections breathe less" (lesson)
  · "the drop feels too slow" (deliberately unmappable). Result:
  - calm end 57.500→55.500 on the timeline table **and** heading; its duration
    token 16.800s→14.800s; start 40.700s unchanged.
  - downstream sections shifted −2.0s on table, heading, step prose, **and** the
    `0.500s` gap notations (e.g. "previous section end (55.500s)"), with the
    `0.500s` token and unchanged durations preserved.
  - close step 8 rewritten; a stale boundary token in a rewrite is retimed by the
    cascade (pinned deterministically in `test_agent`).
  - "the drop feels too slow" left unapplied and named under
    **Unresolved (unapplied)** in the `## Version log` (no anchor + no magnitude).
  - a durable lesson **proposed** (draft id surfaced), not confirmed.
  - `versions/script-draft.edit-brief.v1.md` snapshot == original; frontmatter
    `version: 1 → 2`.

## Deferred

See `docs/v2-refinements-feedback-iteration.md` — prose-retiming residual
collision (attributed retime), guard against LLM-introduced un-anchored numbers,
step-deletion renumbering, the shared artifact-contracts module, richer
timing-conflict model, a lesson confirm surface, beat-grid awareness, richer
feedback segmentation.

## Build Session 2 — orchestrator wrapping (this session)

Wrapped in `orchestrator.tools` per the `edit_brief_draft` / `edit_brief_discover`
precedent. No change to the feedback-iteration package was needed beyond the
wrapping.

- **`feedback_revise(brief_path, feedback)`** — child-budgeted sub-agent tool.
  Calls `feedback_iteration.revise(brief_path, feedback, budget=_child_budget())`.
  Claude-only spend (one mapping/diagnosis call), no external money, no DaVinci
  API → wrappable. Returns status, cost, the version bump, the snapshot path, the
  applied/unresolved items, and the lesson draft ids.
- **`feedback_inspect(brief_path, feedback="")`** — the free op. Calls
  `revise(brief_path, feedback or None, dry_run=True)` (no budget — spends
  nothing): parse + validate + echo the feedback split, version state, and
  snapshot plan.
- **No `search_knowledge` registry entry** — F&I owns no collection (lessons live
  in `user_knowledge`). Both tools record their delegation under the
  `feedback_iteration` label (the stateless-label precedent — `edit_brief` /
  `concept_script`). Graceful degrade: a failure returns a message string, never
  raises into the loop; `_record_delegation` on the active tracker. `feedback-iteration`
  added to the orchestrator's `pyproject.toml` deps + `[tool.uv.sources]` workspace
  entries (mirrors the seven sibling agents); `uv sync` re-locked. Both tools
  registered in `all_tools()`.

### Verification (Build Session 2, recorded)

- **Orchestrator suite:** `47 passed, 1 skipped` (was 44+1; +3 new tests). Ruff
  clean on `packages/orchestrator`. The 3 new tests live in
  `test_subagent_tools.py` alongside the siblings:
  - `feedback_inspect` is free (asserts the entry point is called with
    `{"dry_run": True}` and **no** budget) and records the delegation under
    `feedback_iteration`.
  - `feedback_revise` passes a **derived child budget** (the shared
    `_assert_child_budget` helper) and records under `feedback_iteration`.
  - failure returns a message string, does not raise.
- **Orchestrator-path smoke (recorded, live):** invoked both tools through the
  actual tool-execution path (`.ainvoke` inside an active parent `BudgetTracker`)
  against a copy of `script-draft.edit-brief.md`:
  - `feedback_inspect` — free, spent **$0.0000**, recorded 1 delegation, echoed
    the 4 feedback items + `version=1→2(planned)` + the snapshot plan.
  - `feedback_revise` — **completed, $0.0395**, child-budgeted, recorded the 2nd
    delegation (parent cost rolled up via `add_delegation`), wrote the revision
    **in place**: `version: 1 → 2`, snapshot `versions/script-draft.edit-brief.v1.md`
    == original, calm end 57.500→55.500 with downstream shifted −2.0s, the close
    step rewritten, the "drop" item surfaced unresolved, and a lesson proposed
    (draft id; cleaned up afterward).

## Deferred (orchestrator integration)

See `docs/v2-refinements-feedback-iteration.md`: the tool surface wraps brief path
+ feedback only (`--feedback FILE` / `--max-cost` not threaded); no
`edit-brief → feedback-iteration` chaining (each tool invoked independently); no
remediation entry point registered.

## Phase 2 status

**Complete.** Both build sessions shipped, both smokes recorded, both suites green.
The agent is built and orchestrator-wrapped.
