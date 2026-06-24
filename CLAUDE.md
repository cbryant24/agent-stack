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
├── packages/               # 11 workspace members (see §3)
├── infrastructure/
│   └── docker-compose.yml  # Qdrant (6333/6334) + Jaeger (16686/4318) ONLY
├── scripts/
│   ├── pod                 # RunPod ComfyUI pod create/delete + idle-cost watchdog
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
| `visual-generation` | ComfyUI-backed diffusion collaborator + tutor (free prompt-craft, paid GPU) | `visual-generation` | httpx | [README](packages/visual-generation/README.md) |
| `technique-research` | Goal → prioritized technique domains → delegate gaps to tutorial-research → `TechniqueReport` | `technique-research` | tutorial-research, anthropic, tavily | [README](packages/technique-research/README.md) |
| `edit-brief` ⚠️ | Generates a project `edit-brief.md` (discovery/probe/time-engine); **not in README — status: confirm (§7)** | `edit-brief` | anthropic | [README](packages/edit-brief/README.md) |
| `feedback-iteration` ⚠️ | Applies feedback to iterate prior outputs (lessons/patcher/versioning); **not in README — status: confirm (§7)** | `feedback-iteration` | anthropic | [README](packages/feedback-iteration/README.md) |
| `orchestrator` | **Hub.** Conversational LangGraph ReAct meta-agent; invokes all 8 sibling agents as tools; resumable SQLite-checkpointed chat | `orchestrator` | langgraph, langgraph-checkpoint-sqlite, langchain-anthropic, + all 8 agents | [README](packages/orchestrator/README.md) |

**`agent-runtime`** (shared lib, no CLI): config, OTel tracing, budget tracking, delegation, Qdrant memory + Voyage embeddings, knowledge/`docs_ingest`, reporting, diagnostics, registry. → [README](packages/agent-runtime/README.md). All Python is **≥3.12**.

## 4. Conventions

- **Stack:** Python ≥3.12, uv workspace; Click CLIs; Pydantic v2 models; Anthropic SDK / LangChain + LangGraph; Qdrant + Voyage embeddings; OTel → Jaeger.
- **Dependency manager: `uv` only** — `uv sync --all-packages`. Workspace deps via `[tool.uv.sources]`. Never pip.
- **Running agents:** anything that calls an API must run under `op run --env-file=.env -- uv run …` (1Password resolves the `op://` refs in `.env`); use the `agent()` shell wrapper. Tests & linting use fake keys → plain `uv run`. → README "Running agents".
- **Tests/lint (no CI — run locally):** `uv sync --all-packages && uv run pytest -v` (testpaths=`packages`, importlib mode, pytest-asyncio). `uv run ruff` + `uv run mypy` (config in root/package `pyproject.toml`). Qdrant-dependent tests auto-skip when `localhost:6333` is down; no test needs real API keys.
- **Env vars:** `op://` 1Password references (secrets in the `Personal` vault `credential` field; non-secret paths/URLs as literals). Full list → README "Required Environment Variables" + `.env.example`. Do not duplicate keys here.
- **Output/file conventions:** director artifacts in `~/agent-projects/<slug>/` with **type-only filenames** (`brief.md`, `script.md`, `directed.md`, `visual-batch.md`, `edit-brief.md`). → README "Where should project files live?".

## 5. Pointers (don't copy — link)

- [`README.md`](README.md) — setup + per-agent CLI usage + FAQ
- [`docs/README.md`](docs/README.md) — doc index, organized by longevity
- Living design docs: [`architecture.md`](docs/architecture.md), [`ai-director-agent-system.md`](docs/ai-director-agent-system.md), [`decisions-mode-spec.md`](docs/decisions-mode-spec.md)
- [`docs/visual-generation-known-issues.md`](docs/visual-generation-known-issues.md) — visual-generation limitations
- [`docs/v2-refinements/`](docs/v2-refinements/) — per-agent deferred backlogs · [`docs/handoffs/`](docs/handoffs/) — point-in-time build/research notes (may be stale) · [`docs/templates/`](docs/templates/) — project-plan scaffolds & worked examples
- Per-package `README.md`s (table in §3)

## 6. Current state / gotchas

- **README lags the code.** It lists 8 agents; the repo has **11 packages**. `edit-brief` and `feedback-iteration` exist (and are orchestrator deps) but aren't in the README — see §7.
- **`op run` is required** for any command that hits an API; plain `uv run` passes the literal `op://…` string as the key and fails. Tests are the exception (fake keys).
- **`agent run …` fails** — the `agent` wrapper already includes `uv run`, so `run` becomes `uv run run`. Use `agent <name> <subcommand>`.
- **visual-generation model naming drift:** design docs say Flux (stills) / WAN 2.2 (video), but the built path used **Z-Image-Turbo** (different recipe: cfg≈1, steps≈8, `res_multistep`/`simple`). WAN 2.2 workflow JSON lives in `packages/visual-generation/workflows/`. See `docs/visual-generation-known-issues.md`.
- **No in-repo GPU.** `visual-generation` holds no RunPod credential — you spin up a pod (`scripts/pod up`) and pass `--endpoint <comfyui-url>`. `infrastructure/` is only Qdrant + Jaeger.
- **Qdrant collections (6):** `user_knowledge`, `tutorial_research`, `music_curation_memory`, `voiceover_direction_memory`, `visual_generation_memory`, `technique_research_outputs`. → README "Qdrant Collections".

## 7. Open questions (TODO — fill in)

1. **Status of `edit-brief` and `feedback-iteration`** — phase / test counts / "complete"? They're flagged ⚠️ in §3; resolve and consider adding them to the root README. Their §3 purpose lines are inferred from source modules — correct as needed.
2. Anything else worth pinning here that isn't derivable from the code or linked docs?
