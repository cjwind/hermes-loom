# Hermes Loom — Architecture & design notes

## Module map

```
hermes_loom/
├── config.py         Paths + env overrides. The ONLY place file locations live.
├── ledger.py         The append-only Loom SQLite ledger (owns its own DB).
├── memory_parser.py  Split/join MEMORY.md & USER.md entries ("§" separator).
├── hermes_state.py   READ-ONLY access to Hermes native state (memory, skills, state.db).
├── provenance.py     Best-effort session-window capture from state.db.
├── observer.py       Core: "Hermes changed X" -> ledger event. Decoupled & testable.
├── snapshot.py       Bootstrap import + snapshot-diff fallback.
├── ingest.py         Backfill precise events from state.db tool calls.
├── overrides.py      Manual tuning: write native files safely + record ledger.
├── service.py        Join layer for the API (ledger + live state + provenance).
├── api.py            stdlib http.server JSON API + static UI serving.
├── plugin.py         Hermes plugin: register(ctx), defensive hook binding.
└── cli.py            bootstrap / ingest / reconcile / sync / serve / status.
ui/                   Vanilla-JS SPA (no build step).
tests/                stdlib unittest, sandboxed temp HERMES_HOME + LOOM_DB.
```

## Domain separation (a hard rule)

Three domains, never conflated:

1. **Hermes native state** — `~/.hermes/...`. Owned by Hermes. Read-only from
   Loom *except* the override path, which writes back to the exact files Hermes
   reads. Reads of `state.db` always use `mode=ro`.
2. **Loom ledger** — `~/.hermes-loom/ledger.db`. Owned by Loom. Append-only.
3. **UI / review layer** — talks only to the Local API. Never reaches into Hermes
   or the ledger directly.

`hermes_state.py` is the only reader of native state; `overrides.py` is the only
writer. This keeps the blast radius of any native-file mutation tiny and auditable.

## Why a ledger of *events*, not just state

Hermes already holds final state (the current MEMORY.md). The question "what did
Hermes grow, and where from?" is inherently historical, so Loom records **events**
(`growth_events`) with `before_text`/`after_text` and provenance. Snapshots exist
only to support diffing and revert, not as the primary record.

## Append-only discipline

* `growth_events` rows are immutable in their facts. The single mutable field is
  `status` (`observed → reviewed/edited/reverted/ignored`) — a UI lifecycle flag,
  not history.
* Overrides never edit prior events; they append a `manual_overrides` row **and**
  a new `growth_events` row (`source_hint=manual_override`).
* Snapshots are insert-only.

## Provenance strategy (detail)

`memory` tool calls in `state.db` look like:

```
assistant.tool_calls = [{"function":{"name":"memory",
  "arguments":"{\"action\":\"add\",\"target\":\"user\",\"content\":\"...\"}"}}]
tool message         = {"success": true, "target": "user", "message": "Entry added."}
```

`ingest.py` joins the assistant call to its result via `tool_call_id`, extracts
`action/target/content`, and asks `provenance.capture_session_window(...,
around_ts=ts)` for a window centered on that timestamp. Idempotency is by a
`dedup` key (`statedb:<call_id>`) stored in `metadata_json`.

Skills have no equivalent structured tool-result in this install, so skill
provenance leans on the tool-post hook (when present) and snapshot diff.

## Failure isolation

`observer.Observer` wraps every public method in try/except — a ledger failure
returns `None` instead of raising. `plugin._safe` wraps every callback handed to
Hermes. The plugin imports nothing from Hermes and probes `ctx` with `hasattr`,
so a missing/renamed hook is a no-op, not a crash.

## Concurrency

Hermes is multi-threaded (hooks + a background startup thread share one plugin
ledger). `Ledger` opens its connection with `check_same_thread=False` and
serializes writes with a `threading.Lock`. The API uses `ThreadingHTTPServer` and
opens a fresh `Ledger` per request. Local-first => negligible contention.

## Deliberate non-goals

* Not a new agent platform; not a memory/skills reimplementation.
* No remote API dependency, no auth, no multi-user, no remote deployment.
* No modification of Hermes core. (If a future Hermes build needs a tiny shim to
  expose a memory hook, that would be the *only* candidate change, kept minimal
  and documented — currently not required thanks to the ingest/snapshot fallback.)
