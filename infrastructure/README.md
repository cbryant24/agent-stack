# infrastructure

Docker Compose services for local development.

## Services

| Service | Port(s) | Purpose |
|---|---|---|
| qdrant | 6333 (HTTP), 6334 (gRPC) | Vector store |
| jaeger | 16686 (UI), 4318 (OTLP HTTP) | Distributed tracing |

## Usage

```bash
# Start all services
docker compose up -d

# View logs
docker compose logs -f

# Stop
docker compose down
```

Data is persisted to `~/agent-data/qdrant` via bind-mount. That directory must exist before first `docker compose up` (created by workspace setup).
