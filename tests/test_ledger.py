"""Core ledger behavior: schema, append-only events, snapshots, status updates."""

from base import LoomTestCase


class TestLedger(LoomTestCase):
    def test_add_and_query_event(self):
        led = self.ledger()
        eid = led.add_event(kind="memory_added", target_type="user",
                            action="add", after_text="hi", source_hint="test")
        self.assertGreater(eid, 0)
        ev = led.get_event(eid)
        self.assertEqual(ev["kind"], "memory_added")
        self.assertEqual(ev["after_text"], "hi")

    def test_status_lifecycle(self):
        led = self.ledger()
        eid = led.add_event(kind="memory_added", target_type="user")
        self.assertEqual(led.get_event(eid)["status"], "observed")
        led.update_event_status(eid, "reviewed")
        self.assertEqual(led.get_event(eid)["status"], "reviewed")

    def test_filters(self):
        led = self.ledger()
        led.add_event(kind="memory_added", target_type="user", source_session_id="s1")
        led.add_event(kind="skill_created", target_type="skill", source_session_id="s2")
        self.assertEqual(len(led.query_events(target_type="skill")), 1)
        self.assertEqual(len(led.query_events(session_id="s1")), 1)
        self.assertEqual(len(led.query_events(kind="memory_added")), 1)

    def test_snapshots_roundtrip(self):
        led = self.ledger()
        led.add_memory_snapshot("user", "content v1", "hash1")
        led.add_memory_snapshot("user", "content v2", "hash2")
        latest = led.latest_memory_snapshot("user")
        self.assertEqual(latest["content"], "content v2")

    def test_dedup_helper(self):
        led = self.ledger()
        led.add_event(kind="memory_added", target_type="user", metadata={"dedup": "abc123"})
        self.assertTrue(led.event_exists("abc123"))
        self.assertFalse(led.event_exists("nope"))

    def test_metadata_and_window_json_roundtrip(self):
        led = self.ledger()
        eid = led.add_event(kind="memory_added", target_type="user",
                            metadata={"a": 1}, source_message_window=[{"role": "user"}])
        ev = led.get_event(eid)
        self.assertEqual(ev["metadata"]["a"], 1)
        self.assertEqual(ev["source_message_window"][0]["role"], "user")
