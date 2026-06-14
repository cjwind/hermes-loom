"""The Hermes Loom growth ledger — an append-only SQLite record of how Hermes
grew over time (events), plus the snapshots/overrides needed to diff and revert.

Design rules:
  * ``growth_events`` rows are **append-only** for their factual content
    (before/after/target/source). Only the lifecycle ``status`` column is
    mutable (observed -> reviewed/edited/reverted/ignored).
  * Snapshots are immutable.
  * Manual overrides are append rows; they never mutate prior history.

This module owns *only* the Loom DB. It never touches Hermes native state.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable, Optional

from . import config

# ---- Controlled vocabularies (kept permissive; enforced softly) -------------

KINDS = {
    "memory_added",
    "memory_replaced",
    "memory_removed",
    "skill_created",
    "skill_patched",
    "skill_edited",
    "skill_deleted",
    "memory_snapshot_imported",
    "skill_snapshot_imported",
}
TARGET_TYPES = {"memory", "user", "skill"}
STATUSES = {"observed", "reviewed", "edited", "reverted", "ignored"}
OVERRIDE_TYPES = {"edit", "delete", "reclassify", "annotate"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS growth_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,                 -- when the growth happened (epoch)
    kind TEXT NOT NULL,                      -- see KINDS
    target_type TEXT NOT NULL,               -- memory | user | skill
    target_key TEXT,                         -- entry hash / skill name
    target_path TEXT,                        -- underlying file path
    action TEXT,                             -- raw action (add/replace/remove/...)
    before_text TEXT,
    after_text TEXT,
    source_session_id TEXT,
    source_message_window_json TEXT,         -- best-effort surrounding messages
    source_hint TEXT,                        -- 'plugin_hook' | 'statedb_ingest' | 'snapshot_diff' | 'bootstrap' | 'manual_override'
    tool_name TEXT,
    status TEXT NOT NULL DEFAULT 'observed',
    metadata_json TEXT,
    created_at TEXT NOT NULL                 -- when the row was written (ISO)
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON growth_events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_session ON growth_events(source_session_id);
CREATE INDEX IF NOT EXISTS idx_events_target ON growth_events(target_type, target_key);

CREATE TABLE IF NOT EXISTS memory_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    store_type TEXT NOT NULL,                -- memory | user
    content TEXT,
    snapshot_hash TEXT NOT NULL,
    captured_at REAL NOT NULL,
    source_event_id INTEGER REFERENCES growth_events(id)
);
CREATE INDEX IF NOT EXISTS idx_memsnap_store ON memory_snapshots(store_type, captured_at DESC);

CREATE TABLE IF NOT EXISTS skill_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_name TEXT NOT NULL,
    file_path TEXT,
    content TEXT,
    content_hash TEXT NOT NULL,
    captured_at REAL NOT NULL,
    source_event_id INTEGER REFERENCES growth_events(id)
);
CREATE INDEX IF NOT EXISTS idx_skillsnap_name ON skill_snapshots(skill_name, captured_at DESC);

CREATE TABLE IF NOT EXISTS source_sessions (
    session_id TEXT PRIMARY KEY,
    source TEXT,
    title TEXT,
    started_at REAL,
    ended_at REAL,
    user_id TEXT,
    cached_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS manual_overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_type TEXT NOT NULL,
    target_key TEXT,
    override_type TEXT NOT NULL,             -- edit | delete | reclassify | annotate
    before_text TEXT,
    after_text TEXT,
    reason TEXT,
    applied_at REAL NOT NULL,
    applied_by TEXT
);

CREATE TABLE IF NOT EXISTS loom_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- HOLD: entries parked in Loom only (not in any Hermes file), so they are NOT
-- compiled to MEMORY.md/USER.md. Recategorizing to 暫存 removes the entry from
-- its file and stores it here; moving it back re-inserts it into a file.
CREATE TABLE IF NOT EXISTS held_entries (
    key TEXT PRIMARY KEY,           -- entry_key(text)
    text TEXT NOT NULL,
    from_store TEXT,                -- 'memory' | 'user' (where it came from)
    held_at REAL NOT NULL,
    source_session_id TEXT,
    metadata_json TEXT
);

-- Per-record UI/tuning state for the Inspector: pin, reclassify, annotation.
-- Keyed by (target_type, target_key). Best-effort: memory keys are content
-- hashes, so pins/notes are re-anchored on the new key after an edit.
CREATE TABLE IF NOT EXISTS record_state (
    target_type TEXT NOT NULL,
    target_key TEXT NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 0,
    cat TEXT,                       -- reclassified category override
    annotation TEXT,
    annotation_at REAL,
    reclass_from TEXT,
    reclass_to TEXT,
    reclass_at REAL,
    PRIMARY KEY (target_type, target_key)
);
"""


def _now() -> float:
    return time.time()


class Ledger:
    """Thin wrapper around the Loom SQLite DB."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else config.loom_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Hermes is multi-threaded (hooks + a startup background thread share a
        # plugin's ledger). Allow cross-thread use and serialize writes with a
        # lock so a single Ledger is safe to reuse. Local-first => low contention.
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            # The plugin (in the gateway process) and the API server can open the
            # same ledger.db concurrently; WAL + a busy timeout lets them coexist
            # without transient "database is locked" errors.
            self.conn.execute("PRAGMA busy_timeout=5000")
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # -- meta ----------------------------------------------------------------
    def get_meta(self, key: str) -> Optional[str]:
        row = self.conn.execute("SELECT value FROM loom_meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO loom_meta(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            self.conn.commit()

    # -- growth events -------------------------------------------------------
    def add_event(
        self,
        *,
        kind: str,
        target_type: str,
        action: Optional[str] = None,
        target_key: Optional[str] = None,
        target_path: Optional[str] = None,
        before_text: Optional[str] = None,
        after_text: Optional[str] = None,
        source_session_id: Optional[str] = None,
        source_message_window: Optional[Any] = None,
        source_hint: Optional[str] = None,
        tool_name: Optional[str] = None,
        status: str = "observed",
        metadata: Optional[dict] = None,
        timestamp: Optional[float] = None,
    ) -> int:
        ts = _now() if timestamp is None else float(timestamp)
        window_json = (
            json.dumps(source_message_window, ensure_ascii=False)
            if source_message_window is not None
            else None
        )
        meta_json = json.dumps(metadata, ensure_ascii=False) if metadata else None
        with self._lock:
            cur = self.conn.execute(
                """INSERT INTO growth_events
                   (timestamp, kind, target_type, target_key, target_path, action,
                    before_text, after_text, source_session_id, source_message_window_json,
                    source_hint, tool_name, status, metadata_json, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    ts, kind, target_type, target_key, target_path, action,
                    before_text, after_text, source_session_id, window_json,
                    source_hint, tool_name, status, meta_json,
                    time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts)),
                ),
            )
            self.conn.commit()
            return int(cur.lastrowid)

    def event_exists(self, dedup_key: str) -> bool:
        """Idempotency helper: dedup_key is stored in metadata_json.dedup."""
        row = self.conn.execute(
            "SELECT 1 FROM growth_events WHERE metadata_json LIKE ? LIMIT 1",
            (f'%"dedup": "{dedup_key}"%',),
        ).fetchone()
        return row is not None

    def update_event_status(self, event_id: int, status: str) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE growth_events SET status=? WHERE id=?", (status, event_id)
            )
            self.conn.commit()

    def get_event(self, event_id: int) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM growth_events WHERE id=?", (event_id,)
        ).fetchone()
        return _row_to_event(row) if row else None

    def query_events(
        self,
        *,
        target_type: Optional[str] = None,
        kind: Optional[str] = None,
        status: Optional[str] = None,
        session_id: Optional[str] = None,
        recent_days: Optional[float] = None,
        target_key: Optional[str] = None,
        limit: int = 200,
    ) -> list[dict]:
        where, params = [], []
        if target_type:
            where.append("target_type=?"); params.append(target_type)
        if kind:
            where.append("kind=?"); params.append(kind)
        if status:
            where.append("status=?"); params.append(status)
        if session_id:
            where.append("source_session_id=?"); params.append(session_id)
        if target_key:
            where.append("target_key=?"); params.append(target_key)
        if recent_days is not None:
            where.append("timestamp>=?"); params.append(_now() - recent_days * 86400)
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        params.append(limit)
        rows = self.conn.execute(
            f"SELECT * FROM growth_events{clause} ORDER BY timestamp DESC, id DESC LIMIT ?",
            params,
        ).fetchall()
        return [_row_to_event(r) for r in rows]

    def events_for_target(self, target_type: str, target_key: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM growth_events WHERE target_type=? AND target_key=? "
            "ORDER BY timestamp DESC, id DESC",
            (target_type, target_key),
        ).fetchall()
        return [_row_to_event(r) for r in rows]

    # -- snapshots -----------------------------------------------------------
    def add_memory_snapshot(
        self, store_type: str, content: str, snapshot_hash: str,
        source_event_id: Optional[int] = None, captured_at: Optional[float] = None,
    ) -> int:
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO memory_snapshots(store_type,content,snapshot_hash,captured_at,source_event_id)"
                " VALUES (?,?,?,?,?)",
                (store_type, content, snapshot_hash, captured_at or _now(), source_event_id),
            )
            self.conn.commit()
            return int(cur.lastrowid)

    def latest_memory_snapshot(self, store_type: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM memory_snapshots WHERE store_type=? ORDER BY captured_at DESC, id DESC LIMIT 1",
            (store_type,),
        ).fetchone()
        return dict(row) if row else None

    def add_skill_snapshot(
        self, skill_name: str, file_path: str, content: str, content_hash: str,
        source_event_id: Optional[int] = None, captured_at: Optional[float] = None,
    ) -> int:
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO skill_snapshots(skill_name,file_path,content,content_hash,captured_at,source_event_id)"
                " VALUES (?,?,?,?,?,?)",
                (skill_name, file_path, content, content_hash, captured_at or _now(), source_event_id),
            )
            self.conn.commit()
            return int(cur.lastrowid)

    def latest_skill_snapshot(self, skill_name: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM skill_snapshots WHERE skill_name=? ORDER BY captured_at DESC, id DESC LIMIT 1",
            (skill_name,),
        ).fetchone()
        return dict(row) if row else None

    # -- source sessions cache ----------------------------------------------
    def upsert_session(
        self, session_id: str, source: Optional[str], title: Optional[str],
        started_at: Optional[float], ended_at: Optional[float], user_id: Optional[str],
    ) -> None:
        with self._lock:
            self.conn.execute(
                """INSERT INTO source_sessions(session_id,source,title,started_at,ended_at,user_id,cached_at)
                   VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(session_id) DO UPDATE SET
                     source=excluded.source, title=excluded.title,
                     started_at=excluded.started_at, ended_at=excluded.ended_at,
                     user_id=excluded.user_id, cached_at=excluded.cached_at""",
                (session_id, source, title, started_at, ended_at, user_id, _now()),
            )
            self.conn.commit()

    def get_session(self, session_id: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM source_sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        return dict(row) if row else None

    # -- manual overrides ----------------------------------------------------
    def add_override(
        self, *, target_type: str, target_key: Optional[str], override_type: str,
        before_text: Optional[str], after_text: Optional[str],
        reason: Optional[str], applied_by: str = "loom-ui",
    ) -> int:
        with self._lock:
            cur = self.conn.execute(
                """INSERT INTO manual_overrides
                   (target_type,target_key,override_type,before_text,after_text,reason,applied_at,applied_by)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (target_type, target_key, override_type, before_text, after_text,
                 reason, _now(), applied_by),
            )
            self.conn.commit()
            return int(cur.lastrowid)

    def overrides_for_target(self, target_type: str, target_key: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM manual_overrides WHERE target_type=? AND target_key=? "
            "ORDER BY applied_at DESC",
            (target_type, target_key),
        ).fetchall()
        return [dict(r) for r in rows]

    # -- per-record UI state (pin / reclassify / annotation) -----------------
    def get_record_state(self, target_type: str, target_key: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM record_state WHERE target_type=? AND target_key=?",
            (target_type, target_key),
        ).fetchone()
        return dict(row) if row else None

    def upsert_record_state(self, target_type: str, target_key: str, **fields) -> None:
        cols = ["pinned", "cat", "annotation", "annotation_at",
                "reclass_from", "reclass_to", "reclass_at"]
        cur = self.get_record_state(target_type, target_key) or {}
        merged = {c: cur.get(c) for c in cols}
        merged.update({k: v for k, v in fields.items() if k in cols})
        with self._lock:
            self.conn.execute(
                """INSERT INTO record_state
                   (target_type,target_key,pinned,cat,annotation,annotation_at,
                    reclass_from,reclass_to,reclass_at)
                   VALUES(?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(target_type,target_key) DO UPDATE SET
                     pinned=excluded.pinned, cat=excluded.cat,
                     annotation=excluded.annotation, annotation_at=excluded.annotation_at,
                     reclass_from=excluded.reclass_from, reclass_to=excluded.reclass_to,
                     reclass_at=excluded.reclass_at""",
                (target_type, target_key, int(merged.get("pinned") or 0),
                 merged.get("cat"), merged.get("annotation"), merged.get("annotation_at"),
                 merged.get("reclass_from"), merged.get("reclass_to"), merged.get("reclass_at")),
            )
            self.conn.commit()

    def all_record_states(self) -> dict:
        rows = self.conn.execute("SELECT * FROM record_state").fetchall()
        return {(r["target_type"], r["target_key"]): dict(r) for r in rows}

    # -- held (HOLD) entries — Loom-only, never compiled --------------------
    def add_held(self, key: str, text: str, from_store: Optional[str] = None,
                 source_session_id: Optional[str] = None, held_at: Optional[float] = None) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO held_entries(key,text,from_store,held_at,source_session_id) "
                "VALUES(?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET text=excluded.text, "
                "from_store=excluded.from_store, held_at=excluded.held_at",
                (key, text, from_store, held_at or _now(), source_session_id))
            self.conn.commit()

    def get_held(self, key: str) -> Optional[dict]:
        row = self.conn.execute("SELECT * FROM held_entries WHERE key=?", (key,)).fetchone()
        return dict(row) if row else None

    def list_held(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM held_entries ORDER BY held_at DESC").fetchall()]

    def delete_held(self, key: str) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM held_entries WHERE key=?", (key,))
            self.conn.commit()


def _row_to_event(row: sqlite3.Row) -> dict:
    d = dict(row)
    if d.get("source_message_window_json"):
        try:
            d["source_message_window"] = json.loads(d["source_message_window_json"])
        except (json.JSONDecodeError, TypeError):
            d["source_message_window"] = None
    else:
        d["source_message_window"] = None
    if d.get("metadata_json"):
        try:
            d["metadata"] = json.loads(d["metadata_json"])
        except (json.JSONDecodeError, TypeError):
            d["metadata"] = None
    else:
        d["metadata"] = None
    return d
