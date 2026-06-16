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
- Detect drift between Hermes' live files and Loom's snapshots on a read-only **Status** page

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

### Uninstall

```bash
docker compose down                 # stop the Loom UI

# disable + remove the plugin from ~/.hermes/plugins, then restart Hermes
scripts/uninstall-plugin.sh
```

Your Loom ledger in `~/.hermes-loom` is left untouched — delete that directory too if
you want a clean slate.

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

### AI-assisted tagging (optional)

Loom's recall hook can use an LLM to semantically match a chat message against your
memory tags. It's optional — without it, tagging falls back to offline keyword
matching, which always works.

To enable the LLM path, add the variables below to your Hermes env file at
`~/.hermes/.env`. Loom reads the same file the Hermes gateway loads, and it's already
mounted into the container via `HERMES_HOME` — no compose changes needed. Any
OpenAI-compatible `/chat/completions` endpoint works (hosted or a local server).

```sh
# ~/.hermes/.env
LOOM_LLM_BASE_URL=https://api.openai.com/v1   # required to enable the LLM path (no trailing /chat/completions)
LOOM_LLM_MODEL=gpt-4o-mini                    # required
LOOM_LLM_API_KEY=sk-...                       # optional — omit for keyless local servers (Ollama, LM Studio, …)
LOOM_LLM_MAX_TOKENS=1024                      # optional (default 1024)
LOOM_LLM_TIMEOUT=8                            # optional, seconds (default 8)
```

Both `LOOM_LLM_BASE_URL` and `LOOM_LLM_MODEL` are required to turn the LLM on; the
call is bounded by `LOOM_LLM_TIMEOUT` and silently falls back to keyword matching on
any error. Each recall in the conversation log is tagged with the method it used
(`llm` vs keyword), so you can tell whether the LLM path is active.

## License

MIT
