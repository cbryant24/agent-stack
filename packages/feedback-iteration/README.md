# feedback-iteration

The revision agent. Takes natural-language feedback on a director-owned
`edit-brief.md` and produces a **state-preserving, anchor-addressed, in-place
revision** plus a version trail — and distils durable editing-preference lessons
as a byproduct of the diagnosis.

Revision is the spine; learning hangs off it. One pipeline:

> feedback → moment mapping → diagnosis → targeted patch of the live brief with a
> version-log entry → (when it generalizes) a proposed durable lesson.

## Usage

```
feedback-iteration revise BRIEF.md "feedback text" [--feedback FILE] [--max-cost N] [--dry-run]
```

- Inline feedback and/or a `--feedback FILE` are batched into **one** version bump.
- `--dry-run` is the free op: parse + validate the brief (anchors, frontmatter,
  version state, snapshot plan) and echo the parsed feedback — **no LLM, no
  writes, nothing spent**.

## How it works

- **Foreign-artifact parse.** The brief is parsed by its structure (frontmatter,
  timeline table, `<a id>` anchors, checkbox steps, version log) into char-offset
  spans. This package imports only `agent-runtime` — never `edit-brief`; the
  format is the contract.
- **The LLM never produces a number.** A small pure, fully unit-tested time-shift
  engine recomputes affected timeline rows and cascades downstream boundaries
  (preserving each inter-section gap). The LLM maps feedback to anchors, diagnoses
  the change, rewrites step text, and — for a timing change — names the operation
  and the amount the director *stated*. A numberless timing request is surfaced as
  unresolved, never guessed.
- **Surgical in-place patch.** Only touched sections/rows are spliced; everything
  else is byte-identical, so the director's hand-edits and checked boxes survive.
  A substantively rewritten checked step is unchecked and named as invalidated; a
  mechanical timestamp cascade preserves check state.
- **Versioning.** Before patching, the live brief is snapshot to
  `versions/<stem>.v{N}.md`; `version:` bumps; a `## Version log` entry records
  the feedback, its resolutions, the unresolved items, and any invalidated steps.
- **Lessons.** Durable craft preferences are proposed to `user_knowledge` via
  propose→confirm (domain `editing_preference`) — propose-only; the director gates
  `confirm`.

## Tests

```
uv run pytest packages/feedback-iteration/tests/          # unit + agent + cli
FEEDBACK_ITERATION_SMOKE=1 uv run pytest \                # opt-in live revision
    packages/feedback-iteration/tests/test_smoke_fixture.py -s
```
