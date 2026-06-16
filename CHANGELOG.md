# Changelog

All notable changes to Hermes Loom are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Status (drift) page.** A new read-only "狀態 / Status" nav tab reports, per
  target (`USER.md`, `MEMORY.md`, and each managed skill), whether the live file
  on disk still matches Loom's latest snapshot. Verdicts are exact: an `sha256`
  compare for `in_sync` / `drifted` / `missing_file` / `untracked` /
  `no_baseline`, an entry-level summary derived from `difflib.SequenceMatcher`
  over the `§`-separated entries (added / removed / changed — no key-set
  heuristic), and an expandable `difflib` unified diff. Nothing here writes:
  drift is computed live and clears once `reconcile` / `sync` advances the
  snapshots. New endpoints `GET /api/drift` and `GET /api/drift/<target>`;
  `hermes_loom/drift.py`; `tests/test_drift.py`.

## [0.1.0] - 2026-06-16

First public release. Hermes Loom is a local-first growth observability and tuning
layer for [Hermes Agent](https://gitlab.com/cjwind/hermes-loom): it observes what
Hermes learns across `SOUL.md`, `USER.md`, `MEMORY.md`, and skills, lets you edit /
delete / organize those learnings, and can compile them back into the Hermes runtime
files.

### Added

- **Deposits inspector.** Browse, search, and inspect everything Hermes has
  grown — memory, user preferences, and skills — as "deposits", classified into
  memory / skill / preference. Pin, annotate, edit, delete, and recategorize entries (which
  moves them between `MEMORY.md` and `USER.md`).
  - Full per-entry **edit history** reconstructed from the append-only ledger, with
    expandable version rows and **restore-to-any-version** (history survives
    restores).
  - A **"from this conversation" source block** that shows the originating
    conversation snippet when an exact origin can be traced, with a jump-to-session
    viewer.
- **SOUL.md management.** A Loom-owned, editable copy of the agent identity file with
  DB-stored version history, compiled out to `~/.hermes/SOUL.md` on demand.
- **Memory packs.** A Loom-only middle memory layer: free-text notes with a
  title, tags, and a "when-to-use" field. The
  `pre_llm_call` recall hook resolves the user message against pack tags/titles and
  injects matching packs as context — semantically via an OpenAI-compatible LLM when
  configured, otherwise via offline keyword matching.
- **Conversation log.** An assembled-prompt viewer showing a session's full
  composed request — system prompt (SOUL + memory + skills + tool framing), the
  `pre_llm_call` injected memory, and the conversation messages.
- **Compile.** Regenerate `MEMORY.md` / `USER.md` / every `SKILL.md` / `SOUL.md` from
  the Loom ledger, in place (with timestamped backups) or into a fresh directory.
  Supports historical `--as-of` compiles, and auto-syncs from the live files first so
  output reflects the latest observed state.
- **Hermes plugin integration.** A Hermes 0.16 plugin binding `post_tool_call`,
  `on_session_start`, and `pre_llm_call`; it observes growth live and degrades safely
  when the gateway is unavailable. Growth is also captured offline by ingesting
  Hermes' `state.db` history and by a snapshot-diff reconcile fallback.
- **HOLD.** Park entries in Loom only; they are excluded from compile output.
- **CLI.** `python -m hermes_loom <bootstrap|ingest|reconcile|sync|compile|serve|status>`.
- **Packaging.** pip-installable with the UI bundled and a Hermes plugin entry point;
  Docker / Docker Compose packaging for a containerized install.
- **UI & platform.** Vanilla-JS single-page UI over a stdlib-only Python backend (no
  third-party runtime deps); light/dark theme; full **i18n** (Traditional Chinese +
  English).

### Known limitations

- Memory/user entries are addressed by content hash, so pins, notes, and
  provenance links are re-anchored best-effort after edits.
- Source tracing is best-effort: the originating snippet is only shown when an exact
  match can be resolved; otherwise the deposit is shown without a source block.
- Compile reconstructs files from the latest observed snapshots, so output is only as
  fresh as Loom's last sync — `compile` syncs first by default to mitigate this.
- The Hermes plugin targets the Hermes 0.16 contract.

[0.1.0]: https://gitlab.com/cjwind/hermes-loom/-/tags/v0.1.0
