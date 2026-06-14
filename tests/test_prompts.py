"""Assembled-prompt viewer: read Hermes' per-session ``system_prompt``.

Loom reads the final composed system prompt straight from Hermes' state.db
(read-only) — the prompt that SOUL.md + memories + skills + tool framing
compile into for each conversation. No hook or storage needed; historical
conversations are covered.
"""

import sqlite3

from base import LoomTestCase

from hermes_loom import service


class TestPrompts(LoomTestCase):
    def _make_state(self, rows):
        db = self.hermes_home / "state.db"
        con = sqlite3.connect(str(db))
        con.execute(
            "CREATE TABLE sessions (id TEXT PRIMARY KEY, title TEXT, source TEXT, "
            "model TEXT, provider TEXT, started_at REAL, ended_at REAL, "
            "message_count INTEGER, input_tokens INTEGER, output_tokens INTEGER, "
            "system_prompt TEXT)"
        )
        for r in rows:
            con.execute(
                "INSERT INTO sessions(id,title,source,model,provider,started_at,"
                "ended_at,message_count,input_tokens,output_tokens,system_prompt) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (r["id"], r.get("title"), r.get("source"), r.get("model"),
                 r.get("provider"), r.get("started_at", 1000.0), None,
                 r.get("message_count", 1), None, None, r.get("system_prompt")),
            )
        con.commit()
        con.close()

    def test_list_only_sessions_with_prompt_newest_first(self):
        self._make_state([
            {"id": "s1", "started_at": 100, "system_prompt": "# A\nhello"},
            {"id": "s2", "started_at": 200, "system_prompt": ""},      # excluded
            {"id": "s3", "started_at": 300, "system_prompt": "# B\nworld"},
        ])
        out = service.list_prompts(self.ledger())
        self.assertEqual([s["id"] for s in out["sessions"]], ["s3", "s1"])
        self.assertEqual(out["count"], 2)
        self.assertEqual(out["sessions"][0]["prompt_chars"], len("# B\nworld"))

    def test_detail_returns_prompt_and_outline(self):
        sp = "# SOUL\nidentity\n## Memories\na\n### sub\nb"
        self._make_state([{"id": "x", "started_at": 10, "model": "gpt-5.4", "system_prompt": sp}])
        d = service.prompt_detail(self.ledger(), "x")
        self.assertEqual(d["system_prompt"], sp)
        self.assertEqual(d["model"], "gpt-5.4")
        self.assertEqual([h["text"] for h in d["outline"]], ["SOUL", "Memories", "sub"])
        self.assertEqual([h["level"] for h in d["outline"]], [1, 2, 3])
        self.assertEqual(d["chars"], len(sp))

    def test_detail_missing_session(self):
        self._make_state([{"id": "x", "started_at": 10, "system_prompt": "hi"}])
        self.assertIsNone(service.prompt_detail(self.ledger(), "nope"))

    def test_no_state_db_degrades_gracefully(self):
        led = self.ledger()
        self.assertEqual(service.list_prompts(led)["count"], 0)
        self.assertIsNone(service.prompt_detail(led, "x"))
