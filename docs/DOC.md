# 🧵 Hermes Loom

A **local-first, sidecar growth-observability & tuning layer** for
[Hermes Agent](https://hermes-agent.nousresearch.com).

Hermes already has persistent memory, skills, a session store and the ability to
*automatically* deposit new knowledge. Hermes Loom does **not** replace any
of that. It observes that growth, lets you tune it, and lets you shape what goes
into the prompt — across four UI views:

1. **檢視台 (Inspector)** — *what* did Hermes grow (memory / skills added,
   replaced, removed), *where* it came from (session + conversation window), and
   *how to tune it* (edit / delete / recategorize / annotate, written back to the
   real Hermes files, safely, with snapshots).
2. **SOUL** — edit `SOUL.md` (the agent identity) in Loom's DB and compile it out
   to `~/.hermes/SOUL.md` on demand.
3. **記憶層 (Packs)** — a Loom-only middle memory layer. Each *pack* has a title,
   tags, free-text content, and a "適用時機" (when-to-use) note. The `pre_llm_call`
   hook selects relevant packs from your message and injects them as context.
4. **Prompt** — see the final assembled request of any past conversation: the
   composed system prompt + the full message stream + what was injected.

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
* **`pre_llm_call`** — before every model call, reads the user message, selects
  relevant **packs** (see *Context injection* below), and returns them as context
  for the turn (appended to the user message, **not** the system prompt — so it's
  cache-safe and ephemeral). Each injection is logged to `recall_log`.
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
| `record_state` | per-record UI/tuning state | `pinned`, `cat` (reclassify), `annotation`, `reclass_from/to` |
| `held_entries` | 暫存 (HOLD) entries — Loom-only, never compiled | `key`, `text`, `from_store` |
| `packs` | middle-layer memory packs (context injection) | `title`, `tags_json`, `content`, `when_to_use`, `enabled` |
| `recall_log` | what `pre_llm_call` injected each turn | `session_id`, `message`, `method`, `tags_json`, `records_json` |
| `soul_versions` | append-only SOUL.md edit history (compiled out on demand) | `content`, `content_hash`, `source` |

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
| POST | `/records/pin` | `{target_type, target_key, pinned}` |
| GET | `/status` | auto-deposit status (plugin installed/enabled, gateway running, last live hook) |
| GET | `/packs` | **記憶層**: list packs (title, tags, content, `when_to_use`, enabled) |
| POST | `/packs/save` | create (no `id`) or update (`id`) a pack |
| POST | `/packs/delete` | `{id}` → delete a pack |
| POST | `/recall` | `{message}` → select which packs to inject for a message (used by `pre_llm_call`; also the UI's "test match") |
| GET | `/recall-log` | recent context injections (what the hook injected each turn) |
| GET | `/llm-status[?probe=1]` | whether the pack-selection LLM is configured/working (no secrets) |
| GET | `/soul` | **SOUL**: current DB content + live-file sync status |
| POST | `/soul/save` | `{content, note?}` → store an edited SOUL.md version in the DB |
| POST | `/soul/compile` | write the DB SOUL content out to `~/.hermes/SOUL.md` (backs up first) |
| GET | `/prompts` | **Prompt**: recent conversations that have an assembled system prompt |
| GET | `/prompts/{session_id}` | the final composed system prompt + outline + full messages + injected packs |
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

## Context injection — the pack memory layer (pre_llm_call)

The **記憶層** is a Loom-only middle memory layer, independent of Hermes
memory/skills. Each **pack** has:

- a **title**, **tags**, and free-text **content** (injected verbatim when chosen),
- an optional **適用時機 (`when_to_use`)** note describing the situations it applies to,
- an **enabled** flag (disabled packs are never injected).

CRUD them in the UI (or `GET/POST /api/packs[...]`). The plugin binds Hermes'
**`pre_llm_call`** hook: before every model call it reads the user message,
selects which packs are relevant, and returns their content as context for the
turn (appended to the user message, **not** the system prompt — cache-safe,
ephemeral). This is recall without being a memory provider.

Pack selection (in `tagger.py`):
- **Semantic (LLM)** when an OpenAI-compatible endpoint is configured via env:
  - `LOOM_LLM_BASE_URL` (e.g. `https://api.openai.com/v1`)
  - `LOOM_LLM_MODEL` (e.g. `gpt-4o-mini`)
  - `LOOM_LLM_API_KEY` (optional), `LOOM_LLM_TIMEOUT` (default 8s)
  The model weighs each pack's **title + tags + when_to_use** and returns the ids
  of the packs that apply to the message.
- **Keyword fallback** (a pack matches when its title or any tag is a substring of
  the message) when no LLM is configured, or if the call fails/times out. Always
  offline-safe.

Because the hook runs in the gateway process, set the env vars where the gateway
runs — putting `LOOM_LLM_*` in `~/.hermes/.env` works (Hermes loads it; so does
Loom). It adds one short LLM round-trip per turn when configured; it no-ops
instantly if there are no enabled packs or none match.

Every injection is recorded to `recall_log` (shared ledger), so the UI's **「注入
紀錄」** button (and `GET /api/recall-log`) shows what was injected each turn —
the message, the selected packs, and the method (llm/keyword). Debug the LLM
wiring with `GET /api/llm-status?probe=1`. Test selection live in the 記憶層 view
or with `POST /api/recall {"message": "..."}`.

## SOUL.md management

The **SOUL** view lets Loom own an editable copy of `SOUL.md` (the agent identity,
slot #1 of the system prompt). Editing saves an append-only version to the Loom DB
(`soul_versions`); a separate **compile** step writes the current DB content out to
`~/.hermes/SOUL.md` (backing up the existing file first). Content is stored and
written **byte-for-byte** — Hermes reads SOUL.md as plain text with no entry/§
parsing, so there is no round-trip transform to get wrong. The view shows whether
the live file is in sync with the DB. (`GET /api/soul`, `POST /api/soul/save`,
`POST /api/soul/compile`.)

## Prompt viewer — the final assembled request

The **Prompt** view reconstructs what a past conversation actually sent to the
model, read straight from Hermes' `state.db` (read-only, covers history):

1. **system prompt** — `sessions.system_prompt`, the composed identity + memories
   + skills + tool framing, with a clickable markdown outline.
2. **pre_llm_call injected memory** — the packs Loom injected that session (from
   `recall_log`): the matched message, method, and the injected packs.
3. **conversation messages** — the full `messages` stream (user / assistant /
   tool), with tool calls, token counts and reasoning.

(`GET /api/prompts`, `GET /api/prompts/{session_id}`.)

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
| `test_memory_roundtrip.py` | Loom's memory serialization round-trips through Hermes' `§` delimiter |
| `test_records.py` / `test_hold.py` | Inspector record building, recategorize, 暫存 (HOLD) |
| `test_packs_recall.py` | pack CRUD, `when_to_use`, pack selection (LLM + keyword), recall + hook |
| `test_soul.py` | SOUL.md seed / save / compile (byte-exact round-trip) |
| `test_prompts.py` | assembled-prompt viewer: listing, outline, messages, injected packs |
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
