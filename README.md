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

> Loom is pure Python stdlib, so it has no dependencies to install. Running it in
> a container avoids touching your host Python at all — no `pip install`, and no
> `error: externally-managed-environment` (PEP 668).

### Build the image

```bash
git clone https://gitlab.com/cjwind/hermes-loom.git
cd hermes-loom

docker compose build      # builds the local `hermes-loom` image
```

The container reads/writes two host directories, mounted by Compose:

- your Hermes install → `/hermes` (`HERMES_HOME`)
- Loom's own ledger + snapshots → `/loom` (`LOOM_HOME`), persisted on the host

Passing `UID`/`GID` runs the container as you, so files it writes aren't root-owned.
Export them once per shell to keep the commands short, and pre-create Loom's data
dir so Docker doesn't create it as `root` on first mount:

```bash
export UID="$(id -u)" GID="$(id -g)"
mkdir -p ~/.hermes-loom
```

### Usage

Run one-shot CLI commands with `docker compose run --rm loom <subcommand>`:

```bash
# 1. Seed the ledger: import current memory & skills as a baseline snapshot
docker compose run --rm loom bootstrap

# 2. Backfill past growth events from state.db (precise provenance)
docker compose run --rm loom ingest

# 3. Full refresh in one shot (bootstrap + ingest + snapshot-diff fallback)
docker compose run --rm loom sync

# 4. Show ledger stats
docker compose run --rm loom status

# 5. Start the local UI / API on http://127.0.0.1:8765
docker compose up                         # foreground (Ctrl-C to stop)
docker compose up -d                      # background; `docker compose down` to stop
```

`docker compose up` is the `serve` command — the image's default. It binds
`0.0.0.0` *inside* the container, but Compose only publishes the port to
`127.0.0.1` on your host. To use a different host port, edit the `ports:` line in
`docker-compose.yml` (e.g. `"127.0.0.1:9000:8765"`).

> Prefer plain `docker run`? It works too — just mount the same two volumes:
>
> ```bash
> docker run --rm -it \
>   -u "$(id -u):$(id -g)" \
>   -v "$HOME/.hermes:/hermes" \
>   -v "$HOME/.hermes-loom:/loom" \
>   -p 127.0.0.1:8765:8765 \
>   hermes-loom status        # or: serve / sync / bootstrap / …
> ```

Full subcommands:

| Command | Purpose |
| --- | --- |
| `bootstrap [--force]` | Import current memory + skills as a baseline snapshot |
| `ingest` | Backfill growth events from `state.db` tool calls |
| `reconcile` | Run the snapshot-diff fallback comparison now |
| `sync` | `bootstrap` + `ingest` + `reconcile` (full refresh) |
| `status` | Show the ledger path and per-kind event counts |
| `serve [--host H] [--port P]` | Start the UI / local API |
| `compile [--out DIR \| --in-place] [--as-of ...] [--no-sync]` | Rebuild `MEMORY.md` / `USER.md` / `SKILL.md` / `SOUL.md` from ledger snapshots |

> `compile` writes to a safe `./loom-export` by default and **never** touches `~/.hermes`. Only `--in-place` overwrites the real files, and each file is backed up to `~/.hermes-loom/backups/` before being overwritten.
>
> **In Docker:** the default `./loom-export` lands *inside* the container and is discarded when it exits. To keep a dir export, write it under a mounted volume, e.g. `docker compose run --rm loom compile --out /loom/export` (ends up in `~/.hermes-loom/export` on the host). `--in-place` works as usual — it writes to the mounted `/hermes`, with backups under `/loom/backups`.

### Mount as a live Hermes plugin (optional)

To have Loom observe growth *in real time* via the `post_tool_call` hook, install it into Hermes' plugins directory and enable it:

```bash
# Install into the local ~/.hermes (run on the host, not in the container)
scripts/install-plugin.sh
```

This copies the plugin (`plugin.yaml` + `__init__.py`) into `$HERMES_HOME/plugins/` so Hermes loads it directly — independent of the Loom container, which observes Hermes offline via `state.db` and snapshots.

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
