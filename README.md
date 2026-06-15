# 🧵 Hermes Loom

Hermes Loom is a local-first growth observability and tuning layer for Hermes Agent. See what Hermes learned in memory, skills, and SOUL. Edit, delete, and compile them back into Hermes runtime files.

- **Observes** — what Hermes actually "grew" (memory & skills added / replaced / removed), which conversation it came from, and how it happened;
- **Records provenance** — every growth event is written to Loom's own append-only SQLite ledger, fully separate from Hermes' native state;
- **Tunes** — when *you* ask, writes edits back to the real Hermes files safely (with snapshot backups).

Hermes' native auto-deposit behavior is fully preserved; Loom only observes, and only acts when you tell it to.

## Features

- **Three-tier provenance** — `plugin_hook` (live plugin hook, most precise) → `statedb_ingest` (offline backfill from `state.db` tool calls, precise) → `snapshot_diff` (snapshot-diff inference, fallback).
- **Four UI views**:
  1. **Inspector** — what Hermes grew, where it came from, and in-place tuning (edit / delete / recategorize / annotate).
  2. **SOUL** — edit the agent identity file `SOUL.md` and compile it back out to `~/.hermes/SOUL.md` on demand.
  3. **Packs** — a Loom-only middle memory layer, injected by message semantics on the `pre_llm_call` hook.
  4. **Prompt** — inspect the fully-assembled request of any past conversation (system prompt + message stream + injected context).
- **Two ways to run** — mount it as a live Hermes **plugin**, or run it as a **standalone CLI / service** to analyze an existing `state.db` offline.

## Data layers (never mixed)

```
~/.hermes/                          # Hermes native state (owned by Hermes)
├── memories/{MEMORY.md, USER.md}   #   memory (entries separated by a single-line §)
├── skills/<category>/<skill>/SKILL.md
├── SOUL.md                         #   agent identity
└── state.db                        #   session store (Loom reads only)

~/.hermes-loom/                     # Loom's own state (owned by Loom)
├── ledger.db                       #   append-only growth ledger
└── backups/                        #   snapshot backups taken before writing native files
```

---

## Quick Start

### Requirements

- Python **3.10+**
- A local Hermes install (defaults to `~/.hermes`)

### Install

```bash
# Get the source
git clone https://gitlab.com/cjwind/hermes-loom.git
cd hermes-loom

# Install (no runtime deps; either works)
pip install -e .          # editable, for development
# or
pip install .             # regular install
```

> No install required either: it's pure stdlib, so you can run `python -m hermes_loom <command>` directly.

### Usage

After installing, use the `hermes-loom` console command — or the equivalent `python -m hermes_loom`:

```bash
# 1. Seed the ledger: import current memory & skills as a baseline snapshot
hermes-loom bootstrap

# 2. Backfill past growth events from state.db (precise provenance)
hermes-loom ingest

# 3. Full refresh in one shot (bootstrap + ingest + snapshot-diff fallback)
hermes-loom sync

# 4. Show ledger stats
hermes-loom status

# 5. Start the local UI / API (defaults to 127.0.0.1:8765)
hermes-loom serve
#   open http://127.0.0.1:8765 in your browser
hermes-loom serve --host 0.0.0.0 --port 9000   # custom host / port
```

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

### Mount as a live Hermes plugin (optional)

To have Loom observe growth *in real time* via the `post_tool_call` hook, install it into Hermes' plugins directory and enable it:

```bash
# Install into the local ~/.hermes
scripts/install-plugin.sh

# Or install onto a remote host (over SSH)
scripts/install-plugin.sh <ssh-host>
```

If Loom was installed via `pip install`, Hermes also auto-discovers it through the `hermes_agent.plugins` entry point and calls `register(ctx)` — no manual copying needed.

### Configuration (environment variables)

All paths can be overridden by environment variables (Loom also auto-loads `~/.hermes/.env`):

| Variable | Default | Description |
| --- | --- | --- |
| `HERMES_HOME` | `~/.hermes` | Root of the Hermes native install |
| `LOOM_HOME` | `~/.hermes-loom` | Where Loom keeps its ledger + snapshots |
| `LOOM_DB` | `$LOOM_HOME/ledger.db` | Ledger database path |

---

## Further reading

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — layered architecture & design notes
- [`docs/DOC.md`](docs/DOC.md) — features & data sources
- [`docs/DEMO.md`](docs/DEMO.md) — walkthrough
