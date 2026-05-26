# agent-stack

A uv workspace for a multi-agent AI system. Three specialized agents share a common runtime layer, a Qdrant vector store, and OpenTelemetry-based observability.

## Packages

| Package | Description |
|---|---|
| `agent-runtime` | Shared base types, clients, and utilities used by all agents |
| `tutorial-research` | Agent that researches and synthesizes programming tutorials |
| `music-curation` | Agent that curates and organizes music recommendations |

## Setup

**1. Install dependencies**
```bash
uv sync
```

**2. Copy and fill environment variables**
```bash
cp .env.example .env
# Edit .env — at minimum set ANTHROPIC_API_KEY, VOYAGE_API_KEY, TAVILY_API_KEY
```

**3. Start infrastructure**
```bash
docker compose -f infrastructure/docker-compose.yml up -d
```

**4. Verify**
```bash
curl http://localhost:6333/healthz    # Qdrant
open http://localhost:16686           # Jaeger UI
```

## Workspace Structure

```
agent-stack/
├── pyproject.toml          # workspace root
├── packages/
│   ├── agent-runtime/      # shared runtime
│   ├── tutorial-research/  # tutorial agent
│   └── music-curation/     # music agent
├── infrastructure/         # docker-compose, qdrant config
└── docs/                   # architecture docs
```

## Data Directories

- `~/agent-data/` — local persistence (qdrant storage, run artifacts, sources)
- `~/obsidian/agent-reports/` — agent-generated markdown reports
