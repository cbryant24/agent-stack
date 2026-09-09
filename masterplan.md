# Video Clipping Agent — Masterplan

## Purpose

CLI agent that ingests long-form user video, detects candidate segments cheaply, uses Claude (vision + text) and Whisper to score each segment against a director spec, and cuts the approved segments as clips. Fits agent-stack as a new package alongside `visual-generation`, `voiceover-direction`, `music-curation`.

## Location

- Package: `packages/video-clipping/`
- Memory collection: `video_clipping_memory` (Qdrant, three-type: `run`, `segment`, `lesson`)
- Runs locally on Mac (Apple Silicon). No pod. ffmpeg + `faster-whisper` handle the heavy local work.

## Pipeline

```
video file + spec.yaml
  │
  ├─ 1. PRE-PASS (ffmpeg, no LLM cost)
  │     - silencedetect → silence boundaries
  │     - PySceneDetect ContentDetector → scene cut list A
  │     - ffmpeg scdet filter → scene cut list B (post-process scores → cuts)
  │     - union A ∪ B → visual boundaries; log both lists separately
  │     - ffprobe → resolution, bitrate, framerate
  │     - loudness/RMS → audio quality signal
  │     → candidate_segments[]  (start, end, prepass_metrics, detector_provenance)
  │
  ├─ 2. TRANSCRIBE (faster-whisper, local)
  │     - one pass over full audio, timestamped
  │     - slice transcript by candidate_segments
  │     → segment.transcript, segment.ambient_notes
  │
  ├─ 3. VISION SUMMARY (Claude Sonnet 4.6)
  │     - sample 1 frame per 2s, cap 8 frames per segment
  │     - one call per segment → structured visual summary
  │     → segment.visual_summary
  │
  ├─ 4. DECIDE (Claude Sonnet 4.6, structured output)
  │     - one call per segment
  │     - inputs: spec + prepass_metrics + transcript + visual_summary
  │             + summaries of previously-accepted clips (this run)
  │     - output schema:
  │       { action: "include" | "exclude" | "trim",
  │         refined_start: float, refined_end: float,
  │         exclude_reason: enum | null,
  │         theme_match: 0..1,
  │         confidence: 0..1,
  │         one_line_summary: str }
  │
  ├─ 5. SIMILARITY DEDUPE (Voyage embeddings)
  │     - embed each accepted segment's one_line_summary
  │     - drop if cosine ≥ threshold vs earlier accepted (same run)
  │       or vs prior runs in collection (if --cross-run-dedupe)
  │
  ├─ 6. CUT (ffmpeg, stream copy where possible)
  │     - emit clips to outputs/<run-id>/clips/
  │
  └─ 7. REPORT + MEMORY
        - run report: totals, cost, per-segment table with reasons
        - ingest run + segments + any new lessons into Qdrant
```

## CLI surface

Mirrors `visual-generation` `draft → generate → report`:

- `clip draft <video> --spec spec.yaml` → run pre-pass only; produce a plan file with candidate segments and projected LLM/Whisper cost. No paid calls.
- `clip generate <plan>` → run stages 2–6. Writes clips + run manifest.
- `clip report <run-id>` → renders the run summary from memory.
- `clip explain <question>` → Voyage-embedded semantic search across `video_clipping_memory` (matches agent-stack tutor pattern).

Supporting:

- `clip spec init` → scaffold a spec.yaml.
- `clip model sync` / `clip model list` → local Whisper model registry.

## Spec schema (director's inputs)

```yaml
video: /path/to/source.mp4
location: "Yosemite — Half Dome day hike"
event_type: "hike"
target_clip_length_sec: [15, 60]      # min, max
max_total_output_min: 5                # cap the highlight reel
content_wanted:
  - "landscape and summit views"
  - "wildlife"
  - "moments with people in frame"
exclude_when:
  - low_video_quality       # from prepass_metrics + vision
  - short_or_long           # outside target_clip_length_sec
  - low_audio_quality       # from loudness/RMS + transcript confidence
  - theme_mismatch          # theme_match < 0.5
  - duplicate_of_previous   # similarity dedupe
  - unidentifiable          # vision confidence low
tone_notes: "keep it calm and observational, not action-highlight-reel"
```

The `exclude_when` list is the same taxonomy used as the enum in the decision schema — one source of truth.

## Data model (Pydantic)

- `Spec` — parsed spec.yaml
- `PrepassMetrics` — silence, scenes, resolution, fps, bitrate, mean loudness
- `Segment` — id, start, end, prepass_metrics, transcript, visual_summary, detector_provenance (which detector(s) contributed the boundaries)
- `ClipDecision` — action, refined_start/end, exclude_reason, theme_match, confidence, one_line_summary
- `Run` — id, spec, video hash, segments[], decisions[], cost breakdown

## Package layout

```
packages/video-clipping/
├── README.md
├── pyproject.toml
├── .env.example                       # 1Password refs: ANTHROPIC_API_KEY, VOYAGE_API_KEY, QDRANT_URL
├── src/video_clipping/
│   ├── cli/                           # click commands
│   ├── prepass/                       # ffmpeg + PySceneDetect
│   ├── audio/                         # faster-whisper wrapper
│   ├── vision/                        # frame sampling, Claude Vision calls
│   ├── decide/                        # Claude structured decision
│   ├── similarity/                    # Voyage embed + cosine dedupe
│   ├── cut/                           # ffmpeg segment extraction
│   ├── memory/                        # Qdrant client (mirrors visual-generation)
│   └── models.py                      # Pydantic schemas
├── docs/
│   └── masterplan.md                  # this doc, committed
└── tests/
```

## Phases

- **Phase 0 — scaffolding + pre-pass.** Package skeleton, CLI stubs, `clip draft` end-to-end with ffmpeg/PySceneDetect only. No paid calls. Proof: on a real video, candidate segments look reasonable and cost estimate is printed.
- **Phase 1 — happy path.** `clip generate` runs stages 2–6 on one video for one spec, produces watchable clips, writes a report. Similarity dedupe is intra-run only.
- **Phase 2 — memory + cross-run dedupe.** Ingest into `video_clipping_memory`; add `--cross-run-dedupe`; add `clip explain`.
- **Phase 3 — quality dial-in.** Compare Sonnet vs Opus on the decision call for a fixed segment set; tune frame-sampling density; add lesson pattern for recurring exclude reasons.

MVP = Phases 0 and 1.

## Cost discipline

- Pre-pass is free and gates every paid call — LLM/Whisper only run on candidate segments, never the full video.
- Whisper is local (`faster-whisper`), so audio is effectively free.
- Real cost is Claude vision + decision calls. `clip draft` prints a projected cost from candidate count × frame budget before `generate` runs.
- `clip generate --dry-run` runs the pipeline against pre-pass output without calling Claude, for schema/wiring changes.

## Recommendations on the open choices

- **Whisper: `faster-whisper` local, `small.en` model by default, `medium.en` opt-in.** Free, fast on M-series, no API dependency. High confidence.
- **Claude model: Sonnet 4.6 for both vision summary and decision.** Opus only if Phase 3 comparison shows Sonnet is misclassifying at the boundary. High confidence.
- **Frame sampling: 1 frame per 2 seconds, capped at 8 per segment.** Cheap, and pre-pass already bounds segment length. Medium confidence — revisit in Phase 3.
- **Scene detection: run PySceneDetect ContentDetector AND ffmpeg `scdet` in parallel, union the cut lists, log both separately.** Zero-instrumentation comparison — if the two diverge systematically on real videos, that surfaces the signal without a grading system. Formal preference-learning (grading UI, switching rule) is Phase 3+ material, and only if the divergence proves meaningful. High confidence.
- **Similarity threshold: cosine ≥ 0.88 on Voyage embeddings of `one_line_summary`.** Starting point; tune in Phase 2.
- **Orchestration: straight Python + Click.** No LangChain/LangGraph/n8n. The only stateful loop is the accepted-clips list passed into each decision call, and that's a list — not a graph. High confidence.

## Not in scope for MVP

- Multi-video batch runs
- Music/beat-matched cuts
- Auto-generated titles or captions on output clips
- Web UI
