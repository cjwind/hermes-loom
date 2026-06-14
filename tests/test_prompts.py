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
    def _make_state(self, rows, messages=None):
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
        con.execute(
            "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "session_id TEXT, role TEXT, content TEXT, tool_call_id TEXT, "
            "tool_calls TEXT, tool_name TEXT, token_count INTEGER, "
            "finish_reason TEXT, reasoning TEXT, timestamp REAL)"
        )
        for m in (messages or []):
            con.execute(
                "INSERT INTO messages(session_id,role,content,tool_call_id,tool_calls,"
                "tool_name,token_count,finish_reason,reasoning,timestamp) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (m["session_id"], m.get("role"), m.get("content"), m.get("tool_call_id"),
                 m.get("tool_calls"), m.get("tool_name"), m.get("token_count"),
                 m.get("finish_reason"), m.get("reasoning"), m.get("timestamp", 1000.0)),
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

    def test_detail_includes_messages_and_recalls(self):
        import json
        self._make_state(
            [{"id": "s", "started_at": 10, "system_prompt": "# sys\nhi"}],
            messages=[
                {"session_id": "s", "role": "user", "content": "風浪板對我是什麼", "timestamp": 11},
                {"session_id": "s", "role": "assistant", "content": "",
                 "tool_calls": json.dumps([{"function": {"name": "memory", "arguments": "{\"a\":1}"}}]),
                 "token_count": 42, "timestamp": 12},
                {"session_id": "s", "role": "tool", "tool_name": "memory",
                 "content": "{\"ok\":true}", "tool_call_id": "c1", "timestamp": 13},
            ],
        )
        led = self.ledger()
        led.add_recall(message="風浪板對我是什麼", method="llm", tags=["therapy"],
                       count=1, records=[{"id": "user:x", "value": "陪談有幫助", "tags": ["therapy"]}],
                       session_id="s")
        d = service.prompt_detail(led, "s")
        # messages: full stream, in order, tool_calls parsed
        self.assertEqual([m["role"] for m in d["messages"]], ["user", "assistant", "tool"])
        self.assertEqual(d["messages"][0]["content"], "風浪板對我是什麼")
        self.assertEqual(d["messages"][1]["tool_calls"][0]["name"], "memory")
        self.assertEqual(d["messages"][1]["token_count"], 42)
        self.assertEqual(d["messages"][2]["tool_name"], "memory")
        # recalls: what pre_llm_call injected for this session
        self.assertEqual(len(d["recalls"]), 1)
        self.assertEqual(d["recalls"][0]["tags"], ["therapy"])
        self.assertEqual(d["recalls"][0]["records"][0]["value"], "陪談有幫助")

    def test_detail_missing_session(self):
        self._make_state([{"id": "x", "started_at": 10, "system_prompt": "hi"}])
        self.assertIsNone(service.prompt_detail(self.ledger(), "nope"))

    def test_no_state_db_degrades_gracefully(self):
        led = self.ledger()
        self.assertEqual(service.list_prompts(led)["count"], 0)
        self.assertIsNone(service.prompt_detail(led, "x"))
