# 🧵 Hermes Loom

A **local-first, sidecar growth-observability & tuning layer** for
[Hermes Agent](https://hermes-agent.nousresearch.com).

Hermes already has persistent memory, skills, a session store and the ability to
*automatically* deposit (沉澱) new knowledge. Hermes Loom does **not** replace any
of that. It answers three questions about that growth:

1. **What did Hermes grow?** — what memory entries / skills were recently added,
   replaced or removed.
2. **Where did it come from?** — which session and roughly which part of the
   conversation caused each change.
3. **How do I tune it?** — edit / delete / annotate an entry or a skill, with the
   change written back to the *real* Hermes files (safely, with snapshots).

Hermes' native auto-deposit behavior is preserved. Loom only observes and, when
*you* ask, tunes.

---

## Why no official Hermes management API is required

Hermes does not ship a product-grade remote management API for memory/skills, and
Loom deliberately does **not** assume one. Instead it uses only mechanisms the
official docs already provide:

| Need | Mechanism used |
| --- | --- |
| See current memory | Read `~/.hermes/memories/MEMORY.md` and `USER.md` directly |
| See skills | Read `~/.hermes/skills/<category>/<skill>/SKILL.md` |
| See where growth came from | Read the session store `~/.hermes/state.db` (read-only) |
| Catch changes in real time | A Hermes **plugin** binding `register_hook(...)` |
| Catch changes we couldn't hook | **Snapshot-diff fallback** + **state.db tool-call backfill** |
| Store growth history | Loom's **own** append-only SQLite ledger |

Everything Loom reads from Hermes is opened **read-only**, except the manual
tuning path which writes back to the same files Hermes itself uses.

## Hermes local data sources

```
~/.hermes/
├── memories/
│   ├── MEMORY.md      # assistant persistent memory (may not exist yet)
│   └── USER.md        # facts about the user  (entries separated by a "§" line)
├── skills/
│   └── <category>/<skill>/SKILL.md   # one skill per dir, YAML frontmatter
└── state.db           # SQLite session store: `sessions` + `messages` tables
```

Loom keeps its **own** state completely separate:

```
~/.hermes-loom/          (override with $LOOM_HOME)
├── ledger.db            # the growth ledger (override with $LOOM_DB)
└── backups/             # timestamped file backups taken before each override
```

---

## Architecture

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
                                     │  D. Minimal UI       │  vanilla JS SPA (no build step)
                                     │  /ui/*               │
                                     └──────────────────────┘
```

* **A. Hermes plugin** (`hermes_loom/plugin.py`) — observes memory/skill mutations
  in real time and forwards them to the ledger via `observer.Observer`.
* **B. Loom ledger** (`hermes_loom/ledger.py`) — the append-only record of *growth
  events* (not just final state) + snapshots + overrides.
* **C. Local API** (`hermes_loom/api.py`) — reads the ledger, the live memory/skill
  files and session metadata for the UI; applies overrides.
* **D. UI** (`ui/`) — Recent Growth, Event Detail, Current Memory, Skills, Skill
  Detail, Session Context Viewer.

### The three provenance tiers

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

---

## Quick start

No dependencies to install — Loom is stdlib-only (Python 3.10+).

```bash
cd hermes-loom

# 1. Import current memory + skills as historical snapshots, then backfill
#    precise growth events from the Hermes session store:
python3 -m hermes_loom.cli sync

# 2. Run the local API + UI:
python3 -m hermes_loom.cli serve --port 8765
#   -> open http://127.0.0.1:8765/
```

`status` shows what's in the ledger:

```bash
python3 -m hermes_loom.cli status
```

### CLI commands

| Command | What it does |
| --- | --- |
| `bootstrap [--force]` | Import current memory + skills as `*_snapshot_imported` (historical) |
| `ingest` | Backfill precise growth events from `state.db` tool calls |
| `reconcile` | Run the snapshot-diff fallback now |
| `sync` | `bootstrap` + `ingest` + `reconcile` (full refresh) |
| `serve [--host --port]` | Run the local API + UI |
| `status` | Print event counts by kind |

---

## Install the plugin (live observation)

The plugin is **optional** — `ingest`/`reconcile` already give you visibility.
Install it to capture growth the moment it happens.

The entrypoint is `hermes_loom.plugin:register` (declared in both
`pyproject.toml` under `[project.entry-points."hermes.plugins"]` and
`hermes_plugin.toml`). Depending on your Hermes build:

```bash
# Preferred: Hermes' plugin manager
hermes plugins install /path/to/hermes-loom
hermes plugins list        # should show hermes-loom

# Manual fallback (older builds): point a hook at the registrar in config.yaml
#   hooks:
#     memory_write: hermes_loom.plugin:register   # exact key depends on build
```

`register(ctx)` binds **defensively**: it tries several hook-name aliases per
point (`memory_write`/`on_memory_write`, `tool_post`/`post_tool_call`, …) and
**skips any the running Hermes does not expose**, logging what it bound. It also
spawns the snapshot/ingest fallback once at load, so even a Hermes build that
exposes *zero* bindable hooks still gets coverage. Every callback is wrapped so a
failure is logged and swallowed — **the plugin can never crash Hermes' main
flow.**

### Hook coverage & honesty about limits

Hermes' documented hook surface for memory/skill mutations is not guaranteed to
cover every internal write path, and the exact hook names differ across builds.
Rather than assume a perfect hook, Loom's MVP strategy is explicitly
**"hook + snapshot-diff fallback + state.db ingest"**:

* memory writes → caught by the memory hook **or** by `state.db` ingest (Hermes
  logs the `memory` tool call) **or** by snapshot diff.
* skill writes → caught by the tool-post hook **or** by snapshot diff (skill file
  hashes compared to the last snapshot).

So even in the worst case (no usable hooks), you still see what grew — just via
`statedb_ingest` / `snapshot_diff` instead of `plugin_hook`.

---

## Ledger schema (overview)

Append-only. Event *facts* are never rewritten; only an event's lifecycle
`status` is mutable, and overrides are new append rows.

| Table | Purpose | Key columns |
| --- | --- | --- |
| `growth_events` | every deposit/modification | `kind`, `target_type`, `target_key`, `action`, `before_text`, `after_text`, `source_session_id`, `source_message_window_json`, `source_hint`, `status` |
| `memory_snapshots` | point-in-time MEMORY.md / USER.md | `store_type`, `content`, `snapshot_hash`, `source_event_id` |
| `skill_snapshots` | point-in-time SKILL.md | `skill_name`, `file_path`, `content`, `content_hash` |
| `source_sessions` | cached session metadata (so the UI needn't scan state.db) | `session_id`, `source`, `title`, `started_at` |
| `manual_overrides` | human tuning actions | `target_type`, `target_key`, `override_type`, `before_text`, `after_text`, `reason` |

`kind` ∈ {`memory_added`, `memory_replaced`, `memory_removed`, `skill_created`,
`skill_patched`, `skill_edited`, `skill_deleted`, `memory_snapshot_imported`,
`skill_snapshot_imported`}.
`target_type` ∈ {`memory`, `user`, `skill`}.
`status` ∈ {`observed`, `reviewed`, `edited`, `reverted`, `ignored`}.
`override_type` ∈ {`edit`, `delete`, `reclassify`, `annotate`}.

Full DDL: [`hermes_loom/ledger.py`](hermes_loom/ledger.py). Design notes:
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Local API endpoints

Base: `http://127.0.0.1:8765/api`. No auth (local-first, single user).

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/events` | list growth events; filters: `target_type`, `kind`, `status`, `session_id`, `recent_days`, `limit` |
| GET | `/events/{id}` | event detail: before/after, source session, message window, metadata, related overrides |
| GET | `/memory/current` | current MEMORY.md + USER.md, split into entries |
| GET | `/skills` | skills list + last-change info |
| GET | `/skills/{name}` | one skill + its recent growth events |
| GET | `/sessions/{id}/context` | simplified conversation context from state.db |
| POST | `/overrides/memory/edit` | `{store_type, entry_key, new_text, reason?}` |
| POST | `/overrides/memory/delete` | `{store_type, entry_key, reason?}` |
| POST | `/overrides/skill/edit` | `{name, new_content, reason?}` |
| POST | `/overrides/skill/delete` | `{name, hard?, reason?}` (default = reversible disable) |
| POST | `/maintenance/ingest` | backfill from state.db now |
| POST | `/maintenance/reconcile` | run snapshot-diff now |

---

## Manual tuning safety

Every override **really changes the file Hermes uses** (not just the ledger):

1. The whole file is snapshotted into the ledger **before** any change.
2. A timestamped copy is written to `LOOM_HOME/backups/`.
3. Memory edits are applied at **entry granularity** (addressed by a stable
   content hash) and the file is rewritten atomically — unrelated entries are
   never touched.
4. Skill *disable* is reversible by default (`SKILL.md` → `SKILL.md.disabled`);
   `hard=true` deletes the file (a backup is always kept).
5. On failure, a clear `OverrideError` is raised and the file is left intact.

---

## End-to-end example

```
Hermes writes a memory   → state.db logs the `memory` tool call
                           (or the live plugin hook fires)
      │
      ▼
plugin / `ingest`        → growth_events row:
                           kind=memory_added, after="User likes oolong tea.",
                           source_session_id=sess-demo, source_hint=statedb_ingest,
                           + a 3-message window around the tool call
      │
      ▼
UI "Recent Growth"       → shows the event; Event Detail shows before/after,
                           the source session and the conversation snippet
      │
      ▼
user clicks Edit         → POST /overrides/memory/edit
      │
      ▼
underlying USER.md       → rewritten to "User loves oolong and pu-erh tea."
                           (snapshot + backup taken first)
      │
      ▼
ledger records override  → manual_overrides row (before/after/reason) +
                           a memory_replaced event (source_hint=manual_override)
```

This exact scenario is exercised live in the test suite and reproducible via the
demo in [`docs/DEMO.md`](docs/DEMO.md).

---

## Tests

Stdlib `unittest` — no pytest required:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Coverage maps to the spec:

| Test file | Covers |
| --- | --- |
| `test_ledger.py` | schema, append-only events, snapshots, status lifecycle |
| `test_observer.py` | memory & skill add/replace/remove → events; before/after kept; observer never raises |
| `test_snapshot.py` | bootstrap import + snapshot-diff fallback produce events |
| `test_ingest_provenance.py` | precise events from state.db; session window; session-context lookup |
| `test_overrides.py` | overrides update **both** underlying file and ledger |
| `test_api.py` | event detail over HTTP; override via API changes the file; 400 on bad input |
| `test_plugin.py` | plugin registers against partial/empty/failing `ctx` without crashing |

---

## What is best-effort (not exact)

* **Message window provenance.** Precise message *ids* aren't always available at
  hook time, so we capture a *window* of surrounding messages and a `source_hint`,
  not an exact citation. With `statedb_ingest` the window is centered on the real
  tool-call timestamp; with `plugin_hook` it's the most recent messages.
* **`snapshot_diff` events** are *inferred* (flagged `inferred=true`). A single
  remove+add in one diff is heuristically treated as a replace.
* **Skill mutation hooks.** Exact Hermes skill-write tool names vary by build; the
  plugin matches a known set and otherwise relies on snapshot diff.
* **Plugin hook binding** depends on what the running Hermes exposes; unbound
  points fall back to ingest/snapshot.

These trade-offs are deliberate: the priorities are (1) *see* what Hermes grew,
(2) *roughly* know where it came from, (3) *be able to tune it* — never blocked on
perfect provenance.
