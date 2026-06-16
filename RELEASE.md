# Hermes Loom v0.1.0

**First public release** — 2026-06-16

Hermes Loom is a local-first growth observability and tuning layer for Hermes Agent.
It makes a long-running agent *understandable and controllable*: you can see what
Hermes has learned across `SOUL.md`, `USER.md`, `MEMORY.md`, and skills, edit or prune
those learnings, organize a middle memory layer, and compile everything back into the
Hermes runtime files.

## Highlights

- **Deposits inspector** — browse, search, classify (memory / skill / preference), pin,
  annotate, edit, and delete what Hermes has grown. Recategorizing moves an entry
  between `MEMORY.md` and `USER.md`.
- **Full version history with restore** — every memory/user entry keeps its complete
  edit chain; expand any version to read it, and restore to any point (history is
  preserved across restores).
- **Source tracing** — when a deposit can be pinned to its originating conversation,
  the detail shows that exact snippet with a jump-to-conversation viewer.
- **SOUL.md, owned by Loom** — edit the agent identity file with version history and
  compile it out on demand.
- **Memory packs** — a Loom-only context layer with tags and a "when-to-use"
  field; the recall hook injects matching packs into the prompt, semantically via an
  LLM (optional) or via keyword matching.
- **Conversation log** — inspect a session's fully assembled system prompt
  and exactly what memory was injected each turn.
- **Compile** — regenerate `MEMORY.md` / `USER.md` / `SKILL.md` / `SOUL.md` from the
  ledger, in place (with backups) or into a directory; supports historical `--as-of`.

## Install

Requires Docker (with the Compose plugin) and a local Hermes install (defaults to
`~/.hermes`).

```bash
git clone https://gitlab.com/cjwind/hermes-loom.git
cd hermes-loom

export UID="$(id -u)" GID="$(id -g)"
mkdir -p ~/.hermes-loom

scripts/install-plugin.sh           # copy the plugin into ~/.hermes/plugins, enable + restart Hermes
docker compose build
docker compose run --rm loom sync   # import current memory/skills + backfill history
docker compose up -d                # UI at http://127.0.0.1:8765
```

See the [README](README.md) for configuration, and the optional
AI-assisted tagging setup (`LOOM_LLM_*` in `~/.hermes/.env`).

## Notes & limitations

- The plugin targets the **Hermes 0.16** contract and degrades safely if the gateway
  is unavailable (growth is still backfilled from `state.db` and snapshot diffs).
- Entries are content-hash addressed, so pins/notes/provenance re-anchor best-effort
  after edits.
- Source tracing and the snippet block are best-effort — shown only on an exact match.
- Compile output is only as fresh as Loom's last sync; `compile` syncs first by
  default.

## License

MIT
