# tutorial-research v2 refinements

Items observed during v1 real-world testing that are real limitations but not blockers. Filed for future work, not active.

## Haiku scorer discrimination (calibration, low priority)

Across ~17 real runs, the scorer mostly assigns 5/5 to all candidates — but this is largely because Tavily's results for specific queries are genuinely on-topic, so there's little to discriminate. The scorer DOES discriminate correctly at the edges: it produced 3s and 4s when Tavily surfaced tangential content (an ElevenLabs video for a Suno query, a "love song" tutorial for a generic lyric-writing query). So selection collapses to Tavily-order only when candidates are genuinely uniform in relevance.

Impact: lower than originally filed. When candidates differ in relevance, the scorer separates them. When they're all on-topic, order is effectively Tavily's ranking, which is usually fine but can pick a low-view video over a high-view one.

Optional fix if tighter discrimination is wanted: recalibrate the scoring prompt to distribute scores (most 3, exceptional 5, weak 2) with few-shot examples; and/or add a source-diversity tiebreak (see separate entry) and a view-count tiebreak for same-score candidates.

## No source diversity in candidate selection

**Observed:** When multiple top-scoring candidates come from the same
channel, the planner selects them adjacently. Earlier run selected 2
videos both from "Creatively Make AI Music."

**Impact:** Synthesis pulls from fewer distinct perspectives than the
ingestion budget could afford.

**Likely fix:** Add a diversity bonus to selection — once a channel has
been selected, subsequent candidates from the same channel get a small
score penalty for tie-breaking purposes.

## yt-dlp EJS challenge warnings

**Observed:** Every yt-dlp invocation logs "n challenge solving failed"
warnings. YouTube has started serving JS challenges that require Deno
or Node to solve.

**Impact:** Currently cosmetic for caption-fast-path videos. Will
become a real failure for any video requiring Whisper fallback (since
audio download depends on the format enumeration that the challenge
gates).

**Likely fix:** `brew install deno`. yt-dlp auto-detects it. No code
change required.

## Screenshot extraction has ~20% loss rate

**Observed:** ffmpeg "Screenshot not found, skipping" warnings on 2 of
9 expected screenshots per video on average.

**Impact:** Multimodal embedding count is lower than text-chunk count.
Mostly invisible to retrieval quality but represents lost signal.

**Likely fix:** Investigate why some Claude-suggested timestamps fail
extraction. Likely either past-end-of-video timestamps (need bounds
check) or specific frame positions ffmpeg fails on (need retry with
nearby timestamp).

## Anthropic 529s during candidate scoring

**Observed:** During high-load periods, ~3 of 15 Haiku scoring calls
returned 529 overloaded_error. Agent correctly skipped those candidates
and continued.

**Impact:** Behaves correctly but loses scoring data on those
candidates. With small max_items budgets, could affect selection.

**Likely fix:** Retry once with exponential backoff on 529. Anthropic
SDK supports this natively via `max_retries` parameter — currently
defaulting to 0 retries in the AsyncAnthropic client. Set to 2.

## CLI "Items: 0" in retrieve mode is technically correct but misleading

**Observed:** Retrieve mode shows `Items: 0` even when 10 chunks were
retrieved. "Items" refers to items ingested, not chunks retrieved.

**Impact:** Confusing UX. Now mitigated by the new Retrieved Content
section, but the summary stat is still misleading.

**Likely fix:** In retrieve mode, replace "Items:" with "Chunks
retrieved:" in the CLI summary line.

## RESOLVED (2026-05-28): Synthesis max_tokens truncation

Synthesis was truncating mid-sentence on longer summaries (observed on "Suno meta tags for vocal control", which ended at "...generate or trim meta-tagged lyrics to"). Cause: `max_tokens` was hardcoded to 1024 in synthesis.py; a 900–1500-token synthesis hit the ceiling.

**Fix applied:** `MAX_SYNTHESIS_TOKENS = 8192` constant in constants.py, referenced by synthesis.py. Regression test added asserting the call uses the constant (prevents silent reintroduction of a low cap). Validated by re-running the exact query that truncated — synthesis now completes cleanly. Suite 211 → 214.

## NEW: Sonnet occasionally mangles source IDs in synthesis citations

Observed in melody-writing synthesis: [youtube:2XljmwFCM] appeared where
[youtube:2XljmwvWFCM] was correct — Sonnet dropped characters while
hand-copying the source ID into a citation. The correct ID appeared
properly elsewhere in the same output, so it's a one-off model slip,
not systematic.

Impact: cosmetic for human reading. Would be fragile if citations ever
need to be machine-parseable (auto-linking to source videos).

Possible fix (only if machine-parseable citations become needed): have
synthesis reference sources by index ([1], [2]) and post-substitute
real source_ids programmatically, rather than asking the model to
reproduce IDs verbatim.