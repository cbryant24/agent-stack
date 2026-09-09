# video-clipping — cheatsheet

One-page command reference. See the [README](../README.md) for the full
pipeline description and [masterplan](masterplan.md) for the phase history.

All paid commands need `op run --env-file=.env --` (or the `agent()` shell
wrapper). Free commands run under plain `uv run`.

## Everyday flow

```bash
# 1. Author a spec (once per project).
clip spec init -o spec.yaml
$EDITOR spec.yaml

# 2. Free pre-pass — writes plan.json with projected cost.
clip draft ~/videos/hike.mp4 --spec spec.yaml

# 3. Paid stages — transcribe / vision / decide / dedupe / cut / persist.
agent clip generate <plan.json> --yes

# 4. Rich Markdown report (free; Qdrant-tolerant).
agent clip report <run-id>

# 5. Grounded Q&A over the memory collection.
agent clip explain "which clips feature the piano?"
```

## `clip generate` — key flags

| Flag | Default | When to reach for it |
|---|---|---|
| `--max-usd FLOAT` | `5.00` | Tighten the spend cap. Preflight refuses if `projected_usd > cap`. |
| `--dry-run` | off | Schema / wiring sanity check; cuts every segment, no paid calls. |
| `--cross-run-dedupe` | off | Re-running against the same footage or a re-cut version. |
| `--cross-run-threshold FLOAT` | `0.88` | Loosen if legitimate re-takes get dropped. |
| `--no-lessons` | (on) | Reproducible A/B without the compounding-memory arm. |
| `--yes / -y` | off | Non-interactive shells and cron. |

## `clip explain` — key flags

| Flag | Default | When to reach for it |
|---|---|---|
| `--max-usd FLOAT` | `0.50` | Raise when asking a long question or with `--top-k 20+`. |
| `--top-k INT` | `8` | More hits = more grounding + more cost. |
| `--include-types` | `segment,run,lesson` | Narrow to e.g. `--include-types lesson` for "what have we learned about hikes?" |

Exit codes: `0` ok · `1` Qdrant unavailable · `2` preflight refusal / bad flag.

## Cross-run dedupe — mental model

1. Intra-run dedupe runs first (Phase 1, always on).
2. Only if `--cross-run-dedupe`, each surviving accepted segment is queried
   against every `segment`-type point from **other** runs.
3. First prior hit above the threshold flips the current segment to
   `duplicate_of_previous_run` and records the match in `run.cross_run_hits`
   for the report. The vectors are the ones intra-run dedupe already computed
   — no extra Voyage calls.

## Auto-accrued lessons — when they fire

Both detectors run at the end of every successful `clip generate`:

| Pattern | Trigger | Recorded as |
|---|---|---|
| `exclude_cluster` | ≥ 3 segments this run share an `exclude_reason` (other than duplicate / error) | one `lesson` point |
| `cross_run_repeat` | ≥ 2 cross-run drops point at the same prior `run_id` | one `lesson` point |

Surface back to future runs via `--use-lessons` (on by default) — matching
lessons appear as a `PRIOR LESSONS FOR THIS EVENT TYPE` block in the decide
prompt.

## Qdrant sanity checks

```bash
# Confirm collection exists + point counts by memory_type.
curl -s "$QDRANT_URL/collections/video_clipping_memory/points/count" \
  -H "api-key: $QDRANT_API_KEY" \
  -d '{"filter":{"must":[{"key":"memory_type","match":{"value":"run"}}]}}'

# Scroll the 10 most recent lessons.
curl -s "$QDRANT_URL/collections/video_clipping_memory/points/scroll" \
  -H "api-key: $QDRANT_API_KEY" \
  -d '{"filter":{"must":[{"key":"memory_type","match":{"value":"lesson"}}]},"limit":10}'
```

## Filesystem layout

| Path | What lives there |
|---|---|
| `<agent_data_dir>/video-clipping/outputs/<run-id>/plan.json` | Immutable pre-generate artifact from `clip draft`. |
| `<agent_data_dir>/video-clipping/outputs/<run-id>/run.json` | Post-generate: decisions, clip_paths, status, `qdrant_deviation`, `lessons_recorded`, `cross_run_hits`. |
| `<agent_data_dir>/video-clipping/outputs/<run-id>/clips/` | Cut MP4s. |
| `<agent_data_dir>/video-clipping/outputs/<run-id>/_frames/` | Sampled JPEGs (kept for post-hoc inspection). |
| `<agent_reports_vault>/video-clipping/<date> <title>.md` | Rich report from `clip report`. |
| Qdrant `video_clipping_memory` | `run` / `segment` / `lesson` points; indexed on `memory_type`, `run_id`. |

## Diagnosing weird runs

| Symptom | Where to look |
|---|---|
| Fewer clips than expected | `run.json` → per-decision `action` + `exclude_reason`; report `## Segments` table. |
| Cross-run dedupe over-dropping | Report `## Cross-run dedupe` section; try `--cross-run-threshold 0.92` (stricter). |
| Report shows `(Qdrant unavailable)` | `docker compose -f infrastructure/docker-compose.yml ps` — Qdrant probably down. |
| `run.json` shows `qdrant_deviation: true` | Run completed but memory writes failed. Cut clips + run.json are safe. |
| `clip explain` exits 2 | Preflight cost > `--max-usd`. Raise the cap or lower `--top-k`. |
| Lesson keeps firing on runs you disagree with | Skip lesson surfacing temporarily via `--no-lessons`, delete the offending lesson point via a Qdrant curl. |

## Tests, lint, types

```bash
uv run pytest packages/video-clipping -v          # offline; ffmpeg tests self-skip
uv run ruff check packages/video-clipping
uv run mypy packages/video-clipping/src/video_clipping
```
