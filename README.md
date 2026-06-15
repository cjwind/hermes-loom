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

- Docker (with the Compose plugin)
- A local Hermes install (defaults to `~/.hermes`)

### Get started

```bash
git clone https://gitlab.com/cjwind/hermes-loom.git
cd hermes-loom

# run the container as you, not root
export UID="$(id -u)" GID="$(id -g)"
# Loom's data dir (avoids a root-owned mount)
mkdir -p ~/.hermes-loom

# copies the plugin into ~/.hermes/plugins, then enable + restart Hermes
scripts/install-plugin.sh

docker compose build
docker compose run --rm loom sync       # import current memory/skills + backfill history
docker compose up -d                    # UI at http://127.0.0.1:8765
```

That's it — open <http://127.0.0.1:8765>. Stop with `docker compose down`.

### Common commands

Run any subcommand with `docker compose run --rm loom <cmd>`:

| Command | What it does |
| --- | --- |
| `sync` | Refresh the ledger from current memory/skills + state.db history |
| `status` | Show ledger path and event counts |
| `compile --in-place` | Rebuild Hermes' MEMORY.md / USER.md / SKILL.md / SOUL.md from the ledger (backs up first) |

### Configuration

Both directories are mounted into the container by `docker-compose.yml`:

| Variable | Default (host) | Mounted at | Purpose |
| --- | --- | --- | --- |
| `HERMES_HOME` | `~/.hermes` | `/hermes` | Your Hermes install |
| `LOOM_HOME` | `~/.hermes-loom` | `/loom` | Loom's ledger + snapshots |

To point at a Hermes install elsewhere, set `HERMES_HOME` in your shell before `docker compose …`.

## License

MIT
