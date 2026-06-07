# concept-script v2 refinements

Deferred items from Phase 2. These are **adoption conditions, not rejections** —
each was consciously left out of v1 to keep the MVP lean and to avoid building
mechanisms we can't yet validate. Each entry states the signal that should pull
it forward.

## Addressed in a refinement pass (2026-06-07)

Two `shape`-mode defects surfaced in real-input testing and were **fixed**, not
deferred (recorded here so the durable list stays honest):

- **Self-correction handling is now configurable, preserve-by-default.** Real
  transcripts were being polished — every self-correction resolved away — against
  the agent's "preserve authentic spoken texture" contract. Preserve is now the
  forceful, example-driven default; the shape-only `--clean` flag opts into
  resolving self-corrections into final prose. The flag affects *only*
  self-corrections; disfluency stripping, `director note` execution, and sectioning
  are identical in both modes (`chains.py::_shape_system(clean)`).
- **Cut trailer is now reliable for every executed `director note`.** A global note
  ("remove every 'young' descriptor") executed but recorded no trailer. The prompt
  now mandates one `cuts` entry per executed note in any form (deletion, global /
  repeated change, replacement, reorder; a global change is one summarizing entry),
  and a deterministic safety net warns when the wake phrase is present but no cut
  was recorded. (Serialization already parked the trailer in the skipped preamble.)

The items below remain deferred.

## Knowledge-base reads (user_knowledge / tutorial_research)

**Deferred.** v1 is Claude-only: it reasons from the user's seeds (or transcript)
plus any `--ref` prior script, and reads no memory collection.

**Why deferred:** The agent's contract is to *surface structure, never decide the
creative core* — the user owns content via the seeds. Auto-injecting retrieved
`user_knowledge` facts or `tutorial_research` craft chunks into the generation
prompt is the agent reaching for content the user didn't supply, which works
against that contract (most acutely in generative mode; in curation mode there is
no gap to fill — the transcript is the user's own words). There is also no
feedback signal in v1, so we couldn't tell whether the reads helped or hurt, and
we'd be guessing retrieval limits/thresholds with zero usage data.

**Adoption condition:** a draft comes out demonstrably under-grounded *despite
adequate seeds*, AND the improvement from a read is attributable. This is nearly
identical to the deferred Technique-Research delegation below — treat them
together.

**Backfill cost:** none. It's a thin, read-only addition: a `retrieval.py` that
embeds the seeds and queries `user_knowledge` (+ optionally `tutorial_research`)
in parallel, mirroring the existing pattern in
`music_curation/retrieval.py` and `tutorial_research/retrieval.py` (score-boost +
cap, graceful degrade). No store, no collection — the agent stays stateless.

## Chat / conversational mode

**Deferred.** v1 is single-shot and file-based for both modes. The user steers by
editing the `script.md` he owns and re-running, which is the collaborator-not-
automator ownership model and matches the rest of the stack's `generate → edit →
re-run` loop. The conversational creative surface already exists upstream (Claude
Chat for ideation, Claude Code for development); building chat in would duplicate
it.

**Adoption condition:** the file loop demonstrably fails to let the user steer —
i.e. repeated `draft` re-runs because he can't direct the output without a
conversation. Note this pulls forward the deferred runtime chat work.

## `concept_script_memory` collection

**Deferred.** v1 owns no write-memory collection. The feedback loop that earns one
for `music-curation`/`voiceover-direction` (a `report --reaction` signal
accumulating into lessons) does not exist here — brief quality only surfaces many
steps downstream and attribution back is muddy. A collection with no learning
mechanism is just stored data. The real value memory could serve — prior work as
reference material — is covered in v1 by file reference (`--ref @prior-script.md`).

**Adoption condition:** corpus scale makes manual file reference impractical, OR a
feedback signal emerges worth learning from.

**Backfill cost:** none. Backfill is a batch ingest of existing `script.md` files
(the `music-curation seed ingest` pattern), so deferring carries no penalty.

## Technique Research delegation

**Deferred.** v1 stands alone on Claude plus user-provided references. Technique
Research is not built, and is an upstream enhancement, not a v1 dependency.

**Adoption condition:** Technique Research is built AND a brief needs technique
grounding the user hasn't supplied.
