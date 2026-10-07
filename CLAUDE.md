# CLAUDE.md — agent-stack

Canonical, git-tracked project context for Claude Code. Loaded every session. **Pointers over copies:** this file is the map; the linked READMEs and docs are the territory — read the relevant per-agent README before deep work, and update this file when the shape of the repo changes.

## 1. Project overview

`agent-stack` is a [uv](https://docs.astral.sh/uv/) workspace of domain-specialized AI agents that share one runtime layer (`agent-runtime`), a Qdrant vector store, and OpenTelemetry tracing. The agents cover a creative production pipeline — research → script → voiceover → visuals → edit/feedback — tied together by a conversational LangGraph **`orchestrator`** that invokes the others as tools. The image-generation ("stable diffusion") piece is the **`visual-generation`** agent driving a **user-supplied RunPod ComfyUI pod** over HTTP; there is **no in-repo diffusion server** (the only in-repo infra is Qdrant + Jaeger). Most work is one developer across two machines with separate Claude Code accounts, kept in sync via git — so this file is the shared context.

## 2. Repo layout

```
agent-stack/
├── pyproject.toml          # uv workspace root + pytest config
├── README.md               # per-agent CLI usage (see §5 — note drift in §6)
├── .env / .env.example     # API keys & paths (op:// 1Password refs; not committed)
├── packages/               # 13 workspace members (see §3)
├── infrastructure/
│   └── docker-compose.yml  # Qdrant (6333/6334) + Jaeger (16686/4318) ONLY
├── scripts/
│   ├── pod                 # RunPod ComfyUI (inference) pod create/delete + idle-cost watchdog
│   ├── lora-train          # RunPod ai-toolkit (training) pod + character-LoRA run driver
│   ├── agent_costs.py      # cost reports from trace.jsonl (stdlib; no op run)
│   ├── ingest_user_knowledge.py
│   └── music-curation-report.sh
└── docs/                   # see docs/README.md index (§5)
```

Runtime data lives **outside the repo**: `~/agent-data/` (sources, audio, stills, Qdrant storage, run traces), `~/obsidian/agent-reports/` (generated reports), `~/agent-projects/<slug>/` (director-owned working artifacts). See README "Data Directories" and "Where should project files live?".

## 3. Packages

`agent-runtime` is a shared **library** (no CLI); all other packages depend on it. Run CLI agents with `uv run <cmd>` (wrap in `op run` for anything that calls an API — see §4).

| Package | Purpose | CLI (`uv run …`) | Key deps (beyond agent-runtime) | README |
|---|---|---|---|---|
| `yt-intelligence-pipeline` | YouTube tutorial ingestion → Obsidian notes (human) + Qdrant vectors (agent) | `yt-pipeline` | langchain, anthropic, youtube-transcript-api, yt-dlp, openai-whisper | [README](packages/yt-intelligence-pipeline/README.md) |
| `tutorial-research` | Discovers, ingests & synthesizes tutorial content; queries `tutorial_research` + `user_knowledge` | `tutorial-research` | yt-intelligence-pipeline, anthropic, tavily | [README](packages/tutorial-research/README.md) |
| `music-curation` | Music-theory expert → Suno prompts, persistent taste memory | `music-curation` | anthropic | [README](packages/music-curation/README.md) |
| `voiceover-direction` | ElevenLabs voiceover director (free direction, paid generation, takes + lessons) | `voiceover-direction` | elevenlabs | [README](packages/voiceover-direction/README.md) |
| `concept-script` | Scriptwriting collaborator (seeds or transcript → `script.md`); stateless | `concept-script` | anthropic | [README](packages/concept-script/README.md) |
| `visual-generation` | ComfyUI-backed diffusion collaborator + tutor (free prompt-craft, paid GPU). `visual-generation chat` (alias `visual-agent`, extra `chat`) is a conversation over it: reads, craft, and gated memory writes (evaluations, lessons, facts, canon, registry); never spends on a GPU | `visual-generation` | httpx; extra `chat` (agent-shell) | [README](packages/visual-generation/README.md) |
| `technique-research` | Goal → prioritized technique domains → delegate gaps to tutorial-research → `TechniqueReport` | `technique-research` | tutorial-research, anthropic, tavily | [README](packages/technique-research/README.md) |
| `edit-brief` | Approved `script.md` + artifacts discovered by `project_id` (VO takes, music, assets) + retrieved technique findings → director-owned, time-ordered `edit-brief.md` checklist for a DaVinci Resolve *free* session; all timing computed in code, never by the LLM. Tier-1 (no DaVinci API/automation/delegation), stateless | `edit-brief` | anthropic | [README](packages/edit-brief/README.md) |
| `feedback-iteration` | NL feedback on an `edit-brief.md` → state-preserving, anchor-addressed, in-place revision + version trail; timing recomputed in code (LLM never emits a number); proposes durable `editing_preference` lessons to `user_knowledge`. Stateless | `feedback-iteration` | anthropic | [README](packages/feedback-iteration/README.md) |
| `orchestrator` | **Hub.** Conversational LangGraph ReAct meta-agent; wraps 8 of 10 sibling CLI agents as tools (free/non-side-effecting ops only); `yt-intelligence-pipeline` and `video-clipping` are not wrapped | `orchestrator` | langgraph, langgraph-checkpoint-sqlite, langchain-anthropic, + those 8 agents | [README](packages/orchestrator/README.md) |
| `video-clipping` | Long-form video → highlight clips against a director spec. Free ffmpeg + PySceneDetect pre-pass gates paid stages; faster-whisper transcript, Claude vision+decide per candidate, Voyage intra- and opt-in cross-run dedupe, ffmpeg cut. Auto-persists `run` / `segment` / `lesson` points to `video_clipping_memory` (idempotent uuid5 ids; failures never fail the run); `clip explain` answers grounded questions over that memory | `clip` | pyyaml, scenedetect, faster-whisper | [README](packages/video-clipping/README.md) |
| `agent-shell` | Provider-neutral chat shell core: tool contract + effect classes, approval gate (GPU/memory/destructive), dry-run, audit log, resumable sessions, REPL. Core has **no LLM SDK** (import-linter enforced); the engine is LangGraph on Claude or OpenAI models (extra `agent-shell[langgraph]`), switchable mid-session with history intact. ADR: `docs/adr/0001-agent-shell.md`; plan: `docs/agent-shell/` | `agent-shell demo` | click, prompt-toolkit, rich, + extra `langgraph` (langgraph, langchain-anthropic, langchain-openai) | [README](packages/agent-shell/README.md) |

**`agent-runtime`** (shared lib, no CLI): config, OTel tracing, budget tracking, delegation, Qdrant memory + Voyage embeddings, knowledge/`docs_ingest`, reporting, diagnostics, registry. → [README](packages/agent-runtime/README.md). All Python is **≥3.12**.

## 4. Conventions

- **Stack:** Python ≥3.12, uv workspace; Click CLIs; Pydantic v2 models; Anthropic SDK / LangChain + LangGraph; Qdrant + Voyage embeddings; OTel → Jaeger.
- **Dependency manager: `uv` only** — `uv sync --all-packages`. Workspace deps via `[tool.uv.sources]`. Never pip.
- **Running agents:** anything that calls an API must run under `op run --env-file=.env -- uv run …` (1Password resolves the `op://` refs in `.env`); use the `agent()` shell wrapper. Tests & linting use fake keys → plain `uv run`. → README "Running agents".
- **Tests/lint (no CI — run locally):** `uv sync --all-packages && uv run pytest -v` (testpaths=`packages`, importlib mode, pytest-asyncio). `uv run ruff` + `uv run mypy` (config in root/package `pyproject.toml`). Qdrant-dependent tests auto-skip when `localhost:6333` is down; no test needs real API keys.
- **Env vars:** `op://` 1Password references (secrets in the `Personal` vault `credential` field; non-secret paths/URLs as literals). Full list → README "Required Environment Variables" + `.env.example`. Do not duplicate keys here.
- **Output/file conventions:** director artifacts in `~/agent-projects/<slug>/` with **type-only filenames** (`brief.md`, `script.md`, `directed.md`, `visual-batch.md`, `edit-brief.md`); kebab-case everywhere; ephemeral work → session scratchpad, never repo `tmp/`. → canonical: [`docs/naming-conventions.md`](docs/naming-conventions.md).

## 5. Pointers (don't copy — link)

- [`README.md`](README.md) — setup + per-agent CLI usage + FAQ
- [`docs/README.md`](docs/README.md) — doc index, organized by longevity
- Living design docs: [`architecture.md`](docs/architecture.md), [`ai-director-agent-system.md`](docs/ai-director-agent-system.md), [`decisions-mode-spec.md`](docs/decisions-mode-spec.md)
- [`docs/naming-conventions.md`](docs/naming-conventions.md) — canonical file & folder naming/placement conventions
- [`docs/visual-generation-known-issues.md`](docs/visual-generation-known-issues.md) — visual-generation limitations
- [`docs/v2-refinements/`](docs/v2-refinements/) — per-agent deferred backlogs · [`docs/handoffs/`](docs/handoffs/) — point-in-time build/research notes (may be stale) · [`docs/templates/`](docs/templates/) — project-plan scaffolds & worked examples
- Per-package `README.md`s (table in §3)

## 6. Current state / gotchas

- **`op run` is required** for any command that hits an API; plain `uv run` passes the literal `op://…` string as the key and fails. Tests are the exception (fake keys).
- **Never export `ANTHROPIC_API_KEY` in your shell.** It changes how interactive Claude Code sessions are billed. `agent-shell` passes keys to its model client directly; OpenAI chat uses `CHAT_OPENAI_API_KEY` (add `CHAT_OPENAI_API_KEY=op://…` to `.env`; `.env.example` is blocked from Claude's edits, so add it there yourself).
- **`visual-generation chat` writes drafts to `<AGENT_PROJECTS_DIR>/<slug>/visual-batch.md`**, not the older CLI default (`~/agent-data/visual-generation/batches/<slug>.batch.md`). `AGENT_PROJECTS_DIR` (default `~/agent-projects`) is in `RuntimeConfig`; `project_dir(slug)` validates kebab-case.
- **Evaluations of pre-fix generations are `agent_status=unresolved`** until `EXECUTION_TRUTH_VERIFIED_SINCE=<ISO date>` is set in your environment (the date Gate 0 passes). `visual_generation_memory` now has four `memory_type`s: `generation`, `technique_lesson`, `workflow_template`, `evaluation`.
- **`agent run …` fails** — the `agent` wrapper already includes `uv run`, so `run` becomes `uv run run`. Use `agent <name> <subcommand>`.
- **visual-generation model naming drift:** design docs say Flux (stills) / WAN 2.2 (video), but the built path used **Z-Image-Turbo** (different recipe: cfg≈1, steps≈8, `res_multistep`/`simple`). WAN 2.2 workflow JSON lives in `packages/visual-generation/workflows/`. See `docs/visual-generation-known-issues.md`.
- **No in-repo GPU.** `visual-generation` holds no RunPod credential — you spin up a pod (`scripts/pod up`) and pass `--endpoint <comfyui-url>`. `infrastructure/` is only Qdrant + Jaeger.
- **Qdrant collections (7):** `user_knowledge`, `tutorial_research`, `music_curation_memory`, `voiceover_direction_memory`, `visual_generation_memory`, `technique_research_outputs`, `video_clipping_memory` (three `memory_type` discriminators: `run` / `segment` / `lesson`; payload indices on `memory_type` and `run_id`). → README "Qdrant Collections".

## 7. Session wrap-up

- **End-of-session knowledge check.** After a session with substantial technical work (new infra, an incident diagnosis, a non-trivial implementation — not every session), **ask** whether the user wants a dated point-in-time knowledge-drop doc written to `docs/handoffs/`. Don't create it unprompted. If yes: a narrative covering *why*, not just *what changed*, dense enough that an LLM reading it cold could generate real comprehension questions from it (the user pastes it into a separate chat afterward to quiz themselves and surface gaps). Worked example of the expected shape/depth: [`docs/handoffs/visual-generation-2026-09-20-runpod-global-volume-handoff.md`](docs/handoffs/visual-generation-2026-09-20-runpod-global-volume-handoff.md).
