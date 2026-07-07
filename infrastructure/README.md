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

## Remote access (Qdrant over Tailscale)

The vector DB can run on one machine (e.g. the M1) and be reached from another over Tailscale. Two things must line up — get either wrong and you don't get an error, you get **quietly empty retrievals** (the `tutorial_research` / `user_knowledge` legs degrade silently to empty when Qdrant is unreachable):

1. **Client side** — point `QDRANT_URL` at the host's Tailscale IP in `agent-stack/.env`, e.g. `QDRANT_URL=http://<tailscale-ip>:6333`. This is a plain string, not an `op://` secret, so the `op run --env-file` wrapper still resolves only the API keys. The host comes from `QDRANT_URL` → `RuntimeConfig.qdrant_url` → `AsyncQdrantClient(url=...)`; nothing hardcodes it, so "the DB moved" is a config change, never a code change.
2. **Host side** — bind Qdrant's published port to the **Tailscale interface**, not loopback. In `docker-compose.yml` use `"<tailscale-ip>:6333:6333"`. `"127.0.0.1:6333:6333"` accepts only local connections (a remote client gets *connection refused*); `"0.0.0.0:6333:6333"` exposes it on **every** interface — unsafe, since Qdrant runs with no auth by default. Docker Desktop on macOS only binds a specific IP if that interface exists when the container starts, so **bring Tailscale up before `docker compose up -d`**.

Diagnosing from the client: `nc -vz <host-tailscale-ip> 6333`.

- **`succeeded`** — port is reachable; if retrieval is still empty, look at `QDRANT_URL` or the data.
- **`Connection refused`** — the host answered and rejected the port: nothing listening on that interface → a **bind** problem (you're on `127.0.0.1`, fix the compose bind).
- **`timed out`** — nothing answered: a **network** problem (Tailscale down, wrong IP, host off).
