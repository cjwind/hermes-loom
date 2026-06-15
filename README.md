# 🧵 Hermes Loom

Hermes Loom is a local-first growth observability and tuning layer for Hermes Agent.

It helps you inspect what Hermes has learned across SOUL.md, USER.md, MEMORY.md, and skills, then edit, delete, classify, and compile those changes back into Hermes.

Loom is built for people who want long-running agents to be understandable and controllable, not just increasingly opaque.

## Features

- Inspect Hermes growth across memory, USER.md, SOUL.md, and skills
- Edit or delete bad, stale, or overly specific agent learnings
- Manage SOUL.md as a first-class layer
- Compile Loom-managed records back into Hermes runtime files
- Organize task-specific middle-layer context packs
- Dynamically inject relevant packs for specific tasks
- Inspect prompt composition and context assembly

## Quick Start

### Requirements

- Docker (with the Compose plugin) — that's it; the image is fully self-contained.
- A local Hermes install (defaults to `~/.hermes`)

### Install & Usage

```bash
git clone https://gitlab.com/cjwind/hermes-loom.git
cd hermes-loom

export UID="$(id -u)" GID="$(id -g)"
mkdir -p ~/.hermes-loom

# Install into the local ~/.hermes (run on the host, not in the container)
scripts/install-plugin.sh

docker compose build

# Seed the ledger: import current memory & skills as a baseline snapshot
docker compose run --rm loom bootstrap
# Backfill past growth events from state.db (precise provenance)
docker compose run --rm loom ingest
# Full refresh in one shot (bootstrap + ingest + snapshot-diff fallback)
docker compose run --rm loom sync

# Start the local UI / API on http://127.0.0.1:8765
docker compose up -d
```

### Configuration (environment variables)

All paths are resolved from environment variables (Loom also auto-loads `$HERMES_HOME/.env`). With Docker, `HERMES_HOME` and `LOOM_HOME` are set to the in-container mount points (`/hermes`, `/loom`) by the image; you point them at host directories via the `volumes:` in `docker-compose.yml`:

| Variable | In-container value | Host directory (volume) | Description |
| --- | --- | --- | --- |
| `HERMES_HOME` | `/hermes` | `~/.hermes` (override with host `HERMES_HOME`) | Root of the Hermes native install |
| `LOOM_HOME` | `/loom` | `~/.hermes-loom` (override with host `LOOM_HOME`) | Where Loom keeps its ledger + snapshots |
| `LOOM_DB` | `$LOOM_HOME/ledger.db` | — | Ledger database path |

To mount a Hermes install that lives elsewhere, set `HERMES_HOME` (and/or `LOOM_HOME`) in your host shell before `docker compose …` — Compose substitutes them into the volume paths.

## License

MIT
