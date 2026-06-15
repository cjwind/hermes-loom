# Hermes Loom — Architecture & design notes

Three clearly-separated layers (never mixed):

```
        ┌──────────────────────────── Hermes native state (owned by Hermes) ───────────────────────────┐
        │  ~/.hermes/memories/*.md     ~/.hermes/skills/**/SKILL.md      ~/.hermes/state.db (sessions)  │
        └───────▲─────────────────────────────▲───────────────────────────────────▲────────────────────┘
                │ read+write (overrides only)  │ read-only                          │ read-only
                │                              │                                    │
   ┌────────────┴──────────┐        ┌──────────┴───────────┐            ┌───────────┴────────────┐
   │  A. Hermes plugin     │  write │  B. Loom ledger      │   read     │  provenance / ingest   │
   │  (live hooks)         ├───────►│  (append-only SQLite)│◄───────────┤  (state.db tool calls) │
   │  observer.Observer    │        │  ledger.Ledger       │            └────────────────────────┘
   └───────────────────────┘        └──────────▲───────────┘
                                                │ read/write
                                     ┌──────────┴───────────┐
                                     │  C. Local API        │  stdlib http.server, JSON
                                     │  hermes_loom.api     │
                                     └──────────▲───────────┘
                                                │ fetch()
                                     ┌──────────┴───────────┐
                                     │  D. Inspector UI     │  vanilla JS, design CSS (no build)
                                     │  /ui/*               │
                                     └──────────────────────┘
```

* **A. Hermes plugin** (`hermes_loom/plugin.py`) — observes memory/skill mutations
  in real time and forwards them to the ledger via `observer.Observer`.
* **B. Loom ledger** (`hermes_loom/ledger.py`) — the append-only record of *growth
  events* (not just final state) + snapshots + overrides.
* **C. Local API** (`hermes_loom/api.py`) — reads the ledger, the live memory/skill
  files and session metadata for the UI; applies overrides.
* **D. UI** (`ui/`) — the **檢視台 (Inspector)**: a single master–detail screen
  (left list rail + right provenance pipeline) built to the Claude Design handoff.
  Light/dark themes, character-level diff, version history, and inline
  edit/delete/annotate/reclassify/pin with undo toasts. Vanilla JS, no build step;
  reuses the design's authoritative `loom-theme.css` / `loom-proto.css`.

## The three provenance tiers

Provenance is recorded **at change-time where possible**, with graceful fallback:

1. **`plugin_hook`** — live hook fires; we record the change with its session id
   immediately. *Best, real-time.* Requires the plugin to be loaded by Hermes.
2. **`statedb_ingest`** — offline backfill: Hermes records every `memory` tool
   call in `state.db`, carrying `{action, target, content}` plus the exact
   session + timestamp. We reconstruct precise events *and* a surrounding message
   window. *Precise, works without the plugin* — this is what makes Loom useful
   on day one against an existing install.
3. **`snapshot_diff`** — coarse fallback: compare current files to the last
   snapshot and infer add/replace/remove. Tagged `inferred=true`. *Best-effort.*

> If hooks aren't precise enough, Loom does **not** block on perfect provenance.
> It shows observed events + the snapshot/ingest fallback so the tool is useful
> immediately.


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
