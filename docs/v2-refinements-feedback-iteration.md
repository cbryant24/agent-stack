---
title: feedback-iteration — v2 refinements (deferred)
date: 2026-06-12
type: deferred-list
agent: feedback-iteration
project: agent-stack
---

# feedback-iteration — v2 refinements (deferred)

Adjacent ideas surfaced during Phase 2 Build Session 1. None are MVP scope; each
is recorded with reasoning so the build stayed disciplined.

## Prose-retiming residual collision risk
The downstream prose cascade substitutes only the *changed boundary values* as
whole `N.NNNs` tokens (leading digit/dot guard), so the `0.500s` gap token and
unchanged `duration =` tokens are excluded by construction. A residual risk
remains: a changed boundary value that *coincidentally equals* an unrelated
unchanged number inside the same shifted section would be rewritten. In the real
artifact this does not occur, and the guard makes it rare. **Deferred:** a fully
*attributed* retime (classify each timestamp token by role — start / end /
duration / gap — and retime only the matching role) would eliminate the residual
risk entirely. Cost/benefit didn't justify it for MVP.

## Numbers introduced by an LLM step rewrite
A step rewrite in a section that also moved is retimed against the net cascade
(`retime_text`), so a stale boundary token the LLM copied from the pre-cascade
view is corrected. **Deferred:** if a rewrite introduces a *brand-new* absolute
timestamp not derived from a known boundary, nothing recomputes it — the LLM is
instructed not to author numbers, but there is no hard guard. A follow-up could
reject rewrites that contain un-anchored timestamps, or require step text to
reference boundaries symbolically.

## Step deletion + renumbering
v1 never deletes steps (changed step = rewrite-in-place; new step = append with
the next ordinal, so no renumber is needed). **Deferred:** if a "remove this
step" verb is added, touched-section ordinal renumbering becomes necessary.

## Shared collection/artifact-contracts module
F&I's brief parser is a second consumer of the edit-brief format facts (the first
being edit-brief's own renderer). This strengthens the existing
`docs/v2-refinements-edit-brief.md` idea of a shared read-only
"collection/artifact contracts" module in `agent-runtime` — the format contract
would live once and both the writer and the foreign reader would import it.
Still out of Phase 1/2 scope; a revisit item.

## Richer timing-conflict model
Two timing ops on the *same* section → the later one is surfaced as unresolved
(conflict). Cross-section ops compose correctly via sequential application.
**Deferred:** a fuller model (e.g. two ops whose effects overlap a shared
boundary, or ordering-sensitive composes) is not needed for the batch sizes seen.

## Lesson confirm surface
Lessons are propose-only in v1 (drafts surfaced by id; the director gates
`confirm` out of band via the runtime's draft store). **Deferred:** an explicit
`confirm` / `reject` CLI surface, or orchestrator-driven gating, belongs with the
orchestrator wrapping (Build Session 2+).

## Beat-grid awareness
F&I ignores the brief's beat grid; a timing change does not re-propose beat
alignment for moved boundaries. The smoke brief has no BPM, so this never bites
in MVP. **Deferred:** when a brief carries a beat grid, a retime could surface
new nearest-beat proposals at the shifted boundaries.

## Feedback segmentation
`collect_feedback` splits on newlines / bullets (one line = one item; a single
inline note = one item). **Deferred:** a single line carrying multiple distinct
concerns is treated as one item; richer segmentation (LLM-side or rule-side)
could split it, at the cost of predictability.

## Surfaced during orchestrator integration (Build Session 2)

### The tool surface wraps brief path + feedback only
`feedback_revise` / `feedback_inspect` thread through the brief path and the
feedback text — not `--feedback FILE` or `--max-cost` (the child budget is
derived from the parent envelope, so `--max-cost` is not a tool arg). Mirrors
edit-brief's "wraps the positional only" decision. **Deferred:** a `--feedback
FILE` tool arg if an autonomous source for session notes appears.

### No edit-brief → feedback-iteration chaining
The orchestrator wraps but does not yet **chain** `edit-brief → feedback-iteration`
(draft a brief, then revise it from feedback in one composed turn) — each tool is
invoked independently and the model composes turn-by-turn. The designed chain is
the natural next integration step (same as edit-brief's deferred
`technique-research → edit-brief` chain), and is explicitly out of Build Session 2
scope. A remediation entry point (so a vector-DB diagnostic could delegate a fix
to feedback-iteration) is likewise not built — F&I registers no remediation
handler.
