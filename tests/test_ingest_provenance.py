"""Part 10.6 + provenance — ingest memory events from a synthetic state.db,
with real session window and session metadata."""

import json
from base import LoomTestCase
from hermes_loom import ingest, hermes_state


def memory_tool_call(call_id, action, target, content):
    return json.dumps([{
        "id": call_id, "call_id": call_id, "type": "function",
        "function": {"name": "memory",
                     "arguments": json.dumps({"action": action, "target": target, "content": content})},
    }])


class TestIngest(LoomTestCase):
    def _seed(self):
        sessions = [{"id": "sess-1", "source": "api_server", "title": "growth chat", "started_at": 100.0}]
        messages = [
            {"session_id": "sess-1", "role": "user", "content": "remember I like tea", "timestamp": 101.0},
            {"session_id": "sess-1", "role": "assistant", "content": "",
             "tool_calls": memory_tool_call("call_1", "add", "user", "User likes tea."),
             "timestamp": 102.0},
            {"session_id": "sess-1", "role": "tool", "tool_name": "memory", "tool_call_id": "call_1",
             "content": json.dumps({"success": True, "target": "user", "message": "Entry added."}),
             "timestamp": 102.5},
            {"session_id": "sess-1", "role": "assistant", "content": "Noted!", "timestamp": 103.0},
        ]
        self.make_state_db(sessions, messages)

    def test_ingest_creates_memory_event_with_provenance(self):
        self._seed()
        led = self.ledger()
        res = ingest.ingest_state_db(led)
        self.assertEqual(res["memory_events"], 1)

        ev = led.query_events(kind="memory_added")[0]
        self.assertEqual(ev["source_session_id"], "sess-1")
        self.assertEqual(ev["source_hint"], "statedb_ingest")
        self.assertEqual(ev["after_text"], "User likes tea.")
        self.assertEqual(ev["tool_name"], "memory")
        # provenance window captured around the tool call
        self.assertIsNotNone(ev["source_message_window"])
        roles = [m["role"] for m in ev["source_message_window"]]
        self.assertIn("user", roles)
        # session metadata cached
        self.assertEqual(led.get_session("sess-1")["title"], "growth chat")

    def test_ingest_is_idempotent(self):
        self._seed()
        led = self.ledger()
        ingest.ingest_state_db(led)
        ingest.ingest_state_db(led)
        self.assertEqual(len(led.query_events(kind="memory_added")), 1)

    def test_session_context_lookup(self):
        self._seed()
        ctx = hermes_state.get_session_context("sess-1", limit=10)
        self.assertTrue(ctx["available"])
        self.assertGreaterEqual(len(ctx["messages"]), 3)
        self.assertEqual(ctx["meta"]["title"], "growth chat")
