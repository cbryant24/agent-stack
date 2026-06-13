# First Time Setup

Here's the full first-time setup picture for the visual-generation agent:

## Accounts to create

| Service | What for |
| --- | --- |
| **Anthropic** | Claude API — the agent's LLM (Sonnet for drafting, Haiku for scoring) |
| **Voyage AI** | Embeddings — text (`voyage-3-large`) and multimodal image+caption (`voyage-multimodal-3`) |
| **RunPod** | Pay-per-hour GPU cloud — where ComfyUI runs during image generation |

The following are system-wide (you likely already have them if other agents are set up):

- **Tavily** — web search (used by Tutorial Research, which visual-generation delegates to)
- **ElevenLabs** — not used by this agent directly, but it's in the shared `.env`

---

## Software to install

**On your Mac (the host machine):**

- **`uv`** — the monorepo workspace manager and package runner. Everything is invoked via `uv run`.
- **Python ≥ 3.12** — required by the package.
- **Docker + Docker Compose** — runs Qdrant (vector DB) and Jaeger (observability) locally. The default `QDRANT_URL` is `http://localhost:6333`, which assumes a local Docker container.

**On a RunPod pod (the GPU backend):**

- **ComfyUI** — the node-graph diffusion engine the agent talks to. You install this on the pod when you spin one up; RunPod has pre-built templates that include it. The agent communicates with it via its HTTP API (`/prompt`, `/history`, `/view`, `/object_info`, `/ws`).
- **Models/checkpoints** — e.g. Flux for stills (v1 focus), WAN for video (fast-follow). You install these into ComfyUI on the pod. The agent's `model sync` command reads what's installed via `/object_info` and reconciles a local registry.

You do **not** need a RunPod API key in v1 — pod lifecycle is advisory: the agent tells you what GPU to spin up and when to stop it; you operate the RunPod console yourself.

---

## Configuration

Copy `.env.example` (at the workspace root) to `.env` and fill in:

```
ANTHROPIC_API_KEY=
VOYAGE_API_KEY=
TAVILY_API_KEY=          # for tutorial-research delegations
QDRANT_URL=http://localhost:6333
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
AGENT_DATA_DIR=~/agent-data
AGENT_REPORTS_VAULT=~/obsidian/agent-reports
```

`ElevenLabs` is not used by this agent. `TAVILY` is used indirectly (via tutorial-research delegations when the agent finds knowledge gaps).

The runtime auto-creates the required data directories (`~/agent-data/visual-generation/assets/`, etc.) on first run.

---

## Directory structure the agent expects

The runtime creates these on startup:

- `~/agent-data/` — source docs, run traces, generated assets
- `~/obsidian/agent-reports/` — agent-written reports (separate from your personal vault)

Generated assets land in `~/agent-data/visual-generation/assets/`. Identity-bearing assets (LoRA-tagged generations) go to a separate, write-guarded isolated path under `~/agent-data/` — never the vault, never any synced location.

---

## What you need to do once standing up

1. `docker compose up -d` — start Qdrant + Jaeger.
2. `uv sync` in the workspace root — installs all packages including `visual-generation`.
3. Fill in `.env`.
4. Run `visual-generation fact add` or `visual-generation knowledge ingest-docs <folder>` to seed `comfyui_mechanics` / `runpod_mechanics` facts into `user_knowledge` from any course docs you have.
5. On RunPod: spin up a pod with a ComfyUI template, install your models, export a working API-format workflow JSON, then run `visual-generation workflow register <exported-api.json>` to register it (the agent walks the graph and proposes slot mappings for you to confirm).
6. Run `visual-generation model sync --endpoint <your-pod-url>` to populate the local model/LoRA registry from the pod.

---

## Current status caveat

The agent is **Phase 2 MVP** — 152 tests passing. The data foundation, memory store, model registry, ComfyUI client, and the full `draft → generate → report` turn are built. The CLI (`draft`, `generate`, `report`, `model sync`, `workflow register`, `recall`, `lesson add`, `fact add`, `explain`, `research`) is the live surface. Video/WAN, LoRA training, and RunPod stop-automation are deferred but the architecture is built to accept them.

(partial — per-turn budget was reached)
[turn: $0.4151, 12 tool calls | session so far: $0.4151]
