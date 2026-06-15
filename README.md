# 🧵 Hermes Loom

A **local-first, sidecar growth-observability & tuning layer** for
[Hermes Agent](https://hermes-agent.nousresearch.com).

Hermes already has persistent memory, skills, a session store and the ability to
*automatically* deposit new knowledge. Hermes Loom does **not** replace any
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
| `compile [--out DIR \| --in-place] [--as-of T]` | Rebuild MEMORY.md/USER.md/SKILL.md from ledger snapshots |

---

## Install via pip (distributable)

For anyone else to use Loom without cloning the repo, install the package. It is
still **zero-dependency** (stdlib only), and the wheel bundles the UI:

```bash
pip install hermes-loom            # from a built wheel / PyPI
# or, from a checkout:
pip install .                      # (make install)
make build                         # build dist/*.whl + sdist to hand out
```

`pip install` gives you **both** halves at once:

1. **The service + UI** — a `hermes-loom` console script:
   ```bash
   hermes-loom sync                 # backfill the ledger
   hermes-loom serve --port 8765    # -> http://127.0.0.1:8765/  (UI bundled)
   ```
2. **The Hermes plugin** — auto-discovered. Loom registers an entry point in the
   `hermes_agent.plugins` group, so Hermes finds it via `importlib.metadata` with
   no file copying. Just install it into **the same environment Hermes runs in**,
   enable, and restart:
   ```bash
   hermes plugins list              # hermes-loom appears (source: entrypoint)
   hermes plugins enable hermes-loom
   hermes gateway restart
   ```

> The plugin runs **inside the Hermes gateway process**, so it must be installed
> into Hermes' own Python environment (e.g. its venv / uv environment), not a
> separate one. The standalone `hermes-loom serve` can run anywhere that can read
> `~/.hermes` and the Loom ledger.

---

## Install the plugin (live observation, without pip)

The plugin is **optional** — `ingest`/`reconcile` already give you visibility.
Install it to capture growth the moment it happens.

Besides the pip/entry-point path above, Hermes 0.16 also discovers a plugin from
`$HERMES_HOME/plugins/<dir>/` via a `plugin.yaml` manifest + a sibling
`__init__.py` exposing `register(ctx)`. This repo ships both at its root, so the
repo *is* the plugin directory — handy for installing a working checkout onto a
remote without building a wheel.

`hermes plugins install` only accepts a **Git URL / owner-repo**, so for a local
checkout use the bundled installer (copies the runtime files into the plugins
dir, then you enable + restart):

```bash
# Local Hermes:
scripts/install-plugin.sh
hermes plugins enable hermes-loom
hermes gateway restart            # restart however you run Hermes

# Remote Hermes over SSH (e.g. a Raspberry Pi):
scripts/install-plugin.sh rpi
ssh rpi 'hermes plugins enable hermes-loom && hermes gateway restart'

# Or, if you push this repo to git:
hermes plugins install <git-url> --enable
```

Verify:

```bash
hermes plugins list               # hermes-loom -> enabled
```

### What the plugin binds (verified against Hermes 0.16)

`register(ctx)` binds the **real** hooks Hermes exposes:

* **`post_tool_call`** — memory and skill changes are not dedicated hooks; they
  flow through the `memory` and `skill_manage` *tools*. The callback receives
  `(*, tool_name, args, result, session_id, tool_call_id, **_)`, so Hermes hands
  us the **session id directly** → precise, real-time provenance (`plugin_hook`).
  Failed tool calls and read-only `skill_view` are ignored.
* **`on_session_start`** — runs the bootstrap + snapshot-diff fallback so nothing
  is silently missed.
* a **`loom_sync`** tool (toolset `loom`) you can call from Hermes to reconcile
  the ledger on demand.

Every callback is wrapped so a failure is logged and swallowed — **the plugin can
never crash Hermes' main flow.** It also spawns the fallback once at load, so even
a build that exposes *zero* bindable hooks still gets coverage. (Validated by
loading the plugin under a real Hermes 0.16 venv and firing `post_tool_call`.)

### Defense in depth

Even if a write path isn't hooked, you still see it — Loom layers three sources:
`plugin_hook` (live) → `statedb_ingest` (Hermes logs the `memory` tool call in
`state.db`) → `snapshot_diff` (file-hash comparison). Worst case, growth shows up
via ingest/snapshot instead of the live hook.

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
| GET | `/records` | **Inspector**: live memory/user/skill entries aggregated into records (versions + provenance + Loom category) |
| GET | `/records/{id}` | one record (`id` = `type:key`) with full provenance + skill content |
| POST | `/records/edit` | `{target_type, target_key, new_value}` → new human version, writes the file |
| POST | `/records/delete` | soft-delete (memory entry removed / skill disabled) |
| POST | `/records/add` | `{store_type, text}` → append entry (used for delete-undo) |
| POST | `/records/annotate` | `{target_type, target_key, text}` → private note (Loom-side only) |
| POST | `/records/recategorize` | `{target_type, target_key, to_cat}` → **move** the entry between MEMORY.md/USER.md (記憶↔偏好/暫存) |
| POST | `/records/tags` | `{target_type, target_key, tags: [...]}` → set a record's tags |
| GET | `/tags` | all tags in use |
| POST | `/recall` | `{message}` → resolve relevant tags from a message + return matching records as context (used by the pre_llm_call hook) |
| GET | `/recall-log` | recent context injections (what the hook injected each turn) |
| GET | `/llm-status[?probe=1]` | whether the tag-resolution LLM is configured/working (no secrets) |
| POST | `/records/pin` | `{target_type, target_key, pinned}` |
| POST | `/overrides/memory/edit` | `{store_type, entry_key, new_text, reason?}` |
| POST | `/overrides/memory/delete` | `{store_type, entry_key, reason?}` |
| POST | `/overrides/skill/edit` | `{name, new_content, reason?}` |
| POST | `/overrides/skill/delete` | `{name, hard?, reason?}` (default = reversible disable) |
| POST | `/maintenance/ingest` | backfill from state.db now |
| POST | `/maintenance/reconcile` | run snapshot-diff now |

---

## Compile / restore Hermes files from the ledger

Because Loom stores **full-content** snapshots of every file (`memory_snapshots`,
`skill_snapshots`), it can regenerate Hermes' files from its own DB — Loom doubles
as a regenerable backup:

```bash
python3 -m hermes_loom compile                      # → ./loom-export/ (safe; never touches ~/.hermes)
python3 -m hermes_loom compile --out /tmp/snap      # custom output dir
python3 -m hermes_loom compile --as-of "2026-06-14 12:00"   # historical state
python3 -m hermes_loom compile --in-place           # overwrite the real files (backs up each first)
python3 -m hermes_loom compile --no-sync            # skip the auto-refresh (use last snapshots as-is)
```

**`compile` auto-syncs first by default** — it runs bootstrap + ingest + reconcile
to refresh snapshots from the current live files, so the output always reflects
the latest state (even changes Loom hadn't observed yet). The implicit sync is
skipped when `--as-of` is given (you explicitly want a past state) or with
`--no-sync`.

Category controls where an entry lives: **記憶 → MEMORY.md, 偏好 → USER.md, 暫存
(HOLD) → Loom-only**. Recategorizing a record (UI「改分類」or
`POST /records/recategorize`) physically moves the entry immediately (with
snapshot + backup), so it compiles to the new location. **暫存 (HOLD)** is for
entries you haven't decided about yet: the entry is removed from all Hermes files
and parked in Loom's ledger, so **compile never emits it** until you move it back
to 記憶/偏好.

Default output is a **dir** (`memories/` + `skills/` tree, never modifies
`~/.hermes`). `--in-place` overwrites the live files, taking a timestamped backup
of each into `LOOM_HOME/backups/` first. `--as-of` picks, per file, the newest
snapshot at or before that time (epoch, `YYYY-MM-DD`, or `YYYY-MM-DD HH:MM`).

Reconstruction is byte-exact for anything Loom has snapshotted. (Event-log replay
is *not* used — snapshots are the exact, reliable source; see docs/ARCHITECTURE.md.)

## Tags & context recall (pre_llm_call)

Each record can carry multiple **tags** (UI「標籤」or `POST /records/tags`). The
plugin binds Hermes' **`pre_llm_call`** hook: before every model call it reads the
user's message, resolves which tags are relevant, and injects the matching tagged
records into the turn's context (never the system prompt — cache-safe, ephemeral).
This is recall without being a memory provider.

Tag resolution (in `tagger.py`):
- **Semantic (LLM)** when an OpenAI-compatible endpoint is configured via env:
  - `LOOM_LLM_BASE_URL` (e.g. `https://api.openai.com/v1`)
  - `LOOM_LLM_MODEL` (e.g. `gpt-4o-mini`)
  - `LOOM_LLM_API_KEY` (optional), `LOOM_LLM_TIMEOUT` (default 8s)
  The model is asked to pick relevant tags (verbatim) from the existing tag list.
- **Keyword fallback** (substring match) when no LLM is configured, or if the call
  fails/times out. Always offline-safe.

Because the hook runs in the gateway process, set the env vars where the gateway
runs — putting `LOOM_LLM_*` in `~/.hermes/.env` works (Hermes loads it; so does
Loom). The recall adds one short LLM round-trip per turn when configured; it
no-ops instantly if no tags exist or none match.

Every injection is recorded to `recall_log` (shared ledger), so the UI's **「注入
紀錄」** button (and `GET /api/recall-log`) shows what was injected each turn —
the message, the resolved tags, the method (llm/keyword), and which records. Debug
the LLM wiring with `GET /api/llm-status?probe=1`. Try recall directly with
`POST /api/recall {"message": "..."}`.

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
