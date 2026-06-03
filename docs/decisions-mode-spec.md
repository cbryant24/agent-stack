# Seed Ingest --decisions Mode (follow-up after Session 2 smoke test)

## Motivation
The interactive confirmation flow works and should stay as the primary path.
This adds a non-interactive equivalent so re-ingestion is reproducible and
Claude Code can drive the full flow without a human at a terminal.

## Flags

### --dry-run --emit-decisions <file>
Parse files, build the list of inferred candidates (taste + templates),
emit a YAML or JSON decisions template to <file>. Each candidate gets a
stub entry: `decision: null`, `statement: "<original>"`, `edited_statement: null`.
Does NOT write anything to Qdrant or disk (it's a dry-run).

### --decisions <file>
Load decisions from <file>. For each inferred candidate, apply the loaded
decision through the SAME code path interactive mode uses — same write
logic, same validation, same deferred-queue logic. Only the decision
source changes (file instead of stdin prompt).

Decisions file schema (YAML preferred):
```yaml
taste:
  - id: "t1"           # stable identifier (session_id + statement hash)
    statement: "..."   # original, for human readability
    decision: "y"      # y | n | d | e
    edited_statement:  # only if decision == "e"
templates:
  - id: "p1"
    name: "..."
    decision: "y"      # y | n
```

## Constraints
- Must use the same write code path as interactive mode (not a parallel
  direct-write). If the confirmation-flow write logic changes, --decisions
  mode picks up the change for free.
- --emit-decisions output is deterministic (same parse → same IDs). Use
  session_id + SHA of statement as the stable id so re-runs can be diffed.
  This means a decisions file is version-controllable and diffable: the same
  seed files always produce the same IDs, so a decisions file committed to git
  can be replayed exactly on any machine or after any re-clone.
- Missing-ID handling: if a decisions file references an ID that is no longer
  present in the current parse output (e.g. a bullet was reworded between
  ingestions), emit a warning listing the missing IDs and ask for confirmation
  before proceeding. Apply only the still-matched decisions; treat the missing
  ones as if no decision was supplied — i.e. they fall back to whatever the
  interactive mode would do for that candidate type (taste: prompt; template:
  prompt). Silent skip is wrong (the user believes they made a decision and
  it silently didn't apply); hard error is overkill (one reworded bullet
  would block the entire run).
- This is a follow-up feature. Do not build until the interactive flow is
  confirmed working end-to-end by the smoke test.
