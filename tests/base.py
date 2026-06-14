"""Shared test scaffolding: a sandboxed fake Hermes home + Loom ledger.

Each test gets its own temp ``HERMES_HOME`` and ``LOOM_DB`` via env vars, so the
real ``~/.hermes`` is never touched. We synthesize a minimal but schema-accurate
``state.db`` (sessions + messages) so provenance/ingest paths exercise real SQL.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

# Ensure the package is importable when run as `python -m unittest` from repo root.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


STATE_SCHEMA = """
CREATE TABLE sessions (
    id TEXT PRIMARY KEY, source TEXT NOT NULL, user_id TEXT, model TEXT,
    title TEXT, started_at REAL NOT NULL, ended_at REAL, message_count INTEGER DEFAULT 0,
    cwd TEXT
);
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, role TEXT NOT NULL,
    content TEXT, tool_call_id TEXT, tool_calls TEXT, tool_name TEXT, timestamp REAL NOT NULL
);
"""


class LoomTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.hermes_home = root / "hermes"
        (self.hermes_home / "memories").mkdir(parents=True)
        (self.hermes_home / "skills").mkdir(parents=True)
        self.loom_db = root / "loom" / "ledger.db"
        os.environ["HERMES_HOME"] = str(self.hermes_home)
        os.environ["LOOM_HOME"] = str(root / "loom")
        os.environ["LOOM_DB"] = str(self.loom_db)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in ("HERMES_HOME", "LOOM_HOME", "LOOM_DB")])

    # -- helpers -------------------------------------------------------------
    def write_memory(self, store_type, content):
        name = "MEMORY.md" if store_type == "memory" else "USER.md"
        (self.hermes_home / "memories" / name).write_text(content, encoding="utf-8")

    def write_skill(self, category, name, content):
        d = self.hermes_home / "skills" / category / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(content, encoding="utf-8")
        return d / "SKILL.md"

    def make_state_db(self, sessions, messages):
        """sessions: list of dicts; messages: list of dicts."""
        db = self.hermes_home / "state.db"
        con = sqlite3.connect(str(db))
        con.executescript(STATE_SCHEMA)
        for s in sessions:
            con.execute(
                "INSERT INTO sessions(id,source,user_id,title,started_at,ended_at) VALUES(?,?,?,?,?,?)",
                (s["id"], s.get("source", "api_server"), s.get("user_id"),
                 s.get("title"), s.get("started_at", 1000.0), s.get("ended_at")),
            )
        for m in messages:
            con.execute(
                "INSERT INTO messages(session_id,role,content,tool_call_id,tool_calls,tool_name,timestamp)"
                " VALUES(?,?,?,?,?,?,?)",
                (m["session_id"], m["role"], m.get("content"), m.get("tool_call_id"),
                 m.get("tool_calls"), m.get("tool_name"), m.get("timestamp", 1000.0)),
            )
        con.commit()
        con.close()
        return db

    def ledger(self):
        from hermes_loom.ledger import Ledger
        led = Ledger()
        self.addCleanup(led.close)
        return led
