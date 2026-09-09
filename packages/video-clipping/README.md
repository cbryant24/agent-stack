# video-clipping

CLI agent that ingests long-form user video, cheaply detects candidate segments,
uses Claude vision + Whisper to score each segment against a director spec,
cuts the approved segments as clips, and (Phase 2) writes its own memory —
runs, accepted segments, and auto-accrued lessons — into Qdrant so future runs
dedupe cross-run and improve on the same footage.

**Phases 0 + 1 + 2 shipped.** The full pipeline runs end-to-end; the collection
`video_clipping_memory` is live; `clip explain` answers questions grounded in
retrieved memory.

See [`docs/masterplan.md`](docs/masterplan.md) for the pipeline shape and phase
history, and [`docs/cheatsheet.md`](docs/cheatsheet.md) for a one-page command
reference.

## Install

Member of the agent-stack uv workspace. From the repo root:

```bash
uv sync --all-packages
```

System dependencies: `ffmpeg` and `ffprobe` on `PATH`
(`brew install ffmpeg` on macOS).

## Quick tour

```bash
# 1. Scaffold a spec.
clip spec init -o spec.yaml
# (edit spec.yaml — see the file for every field)

# 2. Free pre-pass: candidate segments + projected cost.
clip draft /path/to/source.mp4 --spec spec.yaml

# 3. Paid stages: transcribe → vision → decide → dedupe → cut → persist.
#    (--yes skips the confirmation prompt.)
op run --env-file=.env -- uv run clip generate <plan.json> --yes

# 4. Rich Markdown report of the run (Qdrant-backed sections included).
op run --env-file=.env -- uv run clip report <run-id>

# 5. Ask a grounded question of the memory collection.
op run --env-file=.env -- uv run clip explain "which clips feature the piano?"
```

## Pipeline (Phase 2)

```
video + spec
   │
   ├─ 1. PRE-PASS (ffmpeg + PySceneDetect)        — free, gates every paid call
   ├─ 2. TRANSCRIBE (faster-whisper, local)       — free
   ├─ 3. VISION SUMMARY (Claude Sonnet, per seg)  — paid
   ├─ 4. DECIDE (Claude Sonnet, structured JSON)  — paid; injects PRIOR LESSONS
   ├─ 5. DEDUPE                                    — Voyage embeddings
   │       ├─ intra-run                            — always
   │       └─ cross-run                            — opt-in (--cross-run-dedupe)
   ├─ 6. CUT (ffmpeg, stream-copy where possible) — free
   └─ 7. PERSIST                                   — Qdrant + report + notify
           - Run point + accepted-segment points   — auto (idempotent uuid5 ids)
           - Lesson points                          — auto (pattern detectors)
```

## Memory (`video_clipping_memory`)

Three `memory_type` discriminators in one collection:

| memory_type | Written when | Vector | Payload highlights |
|---|---|---|---|
| `run` | successful `clip generate` | embed of run summary | spec, prepass_metrics, status, accepted_segment_ids, excluded_reason_counts, lessons_recorded |
| `segment` | per accepted decision | embed of `one_line_summary` | segment_id, run_id, refined_start/end, decision, clip_path |
| `lesson` | auto-accrued from patterns | embed of `human_summary` | source_run_id, pattern_type, pattern_payload, event_type |

Point IDs are deterministic `uuid5(NAMESPACE_VIDEO_CLIPPING, key)` so re-runs
upsert instead of duplicating. Qdrant failures never fail a run — the run is
saved to disk with `qdrant_deviation: true` on `run.json`.

### Auto-accrued lessons

Two pattern detectors run at the end of every successful `clip generate`:

- **`exclude_cluster`** — ≥ 3 segments in one run share an `exclude_reason`
  (other than duplicate/error) → one lesson recorded.
- **`cross_run_repeat`** — ≥ 2 cross-run drops point at the same prior run →
  one lesson recorded.

Lessons are surfaced back into the decide prompt on future runs via
`--use-lessons` (default on) as a `PRIOR LESSONS FOR THIS EVENT TYPE` block.

## Commands

| Command | What it does | Cost surface |
|---|---|---|
| `clip spec init [-o spec.yaml]` | Scaffold a spec | free |
| `clip draft <video> --spec spec.yaml` | Pre-pass, plan.json + projected cost | free |
| `clip generate <plan> [flags below]` | Run stages 2–6 + Qdrant persist | Claude + Voyage |
| `clip report <run-id>` | Rich Markdown report (Qdrant-tolerant) | free |
| `clip explain <question> [flags below]` | Grounded semantic-search tutor | one Sonnet call |

### `clip generate` flags

| Flag | Default | Purpose |
|---|---|---|
| `--max-usd FLOAT` | `5.00` | Per-invocation spend cap; preflight refusal if plan projection > cap. |
| `--whisper-model {small.en,medium.en}` | `small.en` | faster-whisper model. |
| `--dry-run` | off | Skip Whisper/vision/decide/embed; cut every segment as-is. |
| `--yes / -y` | off | Skip the confirmation prompt. |
| `--cross-run-dedupe / --no-cross-run-dedupe` | off | Drop clips near-duplicating any accepted clip from prior runs. |
| `--cross-run-threshold FLOAT` | `0.88` | Cosine threshold for cross-run duplicate. |
| `--use-lessons / --no-lessons` | on | Surface prior lessons into the decide prompt. |

### `clip explain` flags

| Flag | Default | Purpose |
|---|---|---|
| `--max-usd FLOAT` | `0.50` | Per-invocation cap; **preflight refusal** (exit 2) if projected > cap. |
| `--top-k INT` | `8` | Total hits across `--include-types`, merged and reranked. |
| `--include-types` | `segment,run,lesson` | Comma-separated memory_types to query. |

Exit codes: `0` success, `1` Qdrant unavailable, `2` preflight or bad flag.

## Where things live

- Plans/runs/clips: `<agent_data_dir>/video-clipping/outputs/<run-id>/`
  (`plan.json`, `run.json`, `clips/`, `_frames/`).
- Reports: `<agent_reports_vault>/video-clipping/<date> <title>.md`.
- Memory: Qdrant at `$QDRANT_URL`, collection `video_clipping_memory`.

## Tests

```bash
uv run pytest packages/video-clipping -v
```

All tests run offline. ffmpeg-dependent tests self-skip if ffmpeg isn't on
PATH. Qdrant is faked via `tests/fakes.py::FakeMemoryStore` — no live Qdrant
required.
