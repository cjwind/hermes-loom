"""Source-trace provenance: status and graceful fallbacks.

These cover the Inspector "source trust" UX — that each record reports *how
well* it can be traced (exact / window / imported / external / inferred /
missing), not just whether a snippet was found.
"""

from base import LoomTestCase
from hermes_loom import service, snapshot
from hermes_loom.memory_parser import entry_key
from hermes_loom.observer import Observer


class TestSourceTrace(LoomTestCase):
    def _detail(self, store, text):
        return service.record_detail(self.ledger(), f"{store}:{entry_key(text)}")

    # 1. exact source match -----------------------------------------------------
    def test_exact_match_with_snippet(self):
        self.write_memory("user", "I like tea.")
        led = self.ledger()
        led.add_event(
            kind="memory_added", target_type="user", action="add",
            target_key=entry_key("I like tea."), after_text="I like tea.",
            source_hint="plugin_hook", source_session_id="s1",
            source_message_window=[{"role": "user", "snippet": "do I like tea?", "timestamp": 1.0}],
        )
        led.upsert_session(session_id="s1", source="api_server", title="Tea chat",
                           started_at=1.0, ended_at=None, user_id=None)
        p = service.record_detail(led, "user:" + entry_key("I like tea."))["provenance"]
        self.assertEqual(p["status"], "exact_match")
        self.assertEqual(p["observed"], "runtime")
        self.assertTrue(p["has_snippet"])
        self.assertEqual(p["snippet"], "do I like tea?")
        self.assertEqual(p["session_id"], "s1")
        self.assertEqual(p["session_title"], "Tea chat")
        self.assertIsNone(p["fallback_reason"])
        self.assertTrue(p["last_traced_at"])

    # 2. only a session window --------------------------------------------------
    def test_window_match_without_snippet(self):
        self.write_memory("user", "Likes oolong.")
        led = self.ledger()
        led.add_event(
            kind="memory_added", target_type="user", action="add",
            target_key=entry_key("Likes oolong."), after_text="Likes oolong.",
            source_hint="statedb_ingest", source_session_id="s2",
            # a window exists, but no user/assistant snippet to pin to
            source_message_window=[{"role": "tool", "tool_name": "memory", "snippet": "", "timestamp": 1.0}],
        )
        p = service.record_detail(led, "user:" + entry_key("Likes oolong."))["provenance"]
        self.assertEqual(p["status"], "window_match")
        self.assertFalse(p["has_snippet"])
        self.assertTrue(p["has_window"])
        self.assertEqual(p["fallback_reason"], "fallback.window")

    # 3. bootstrap / snapshot import -------------------------------------------
    def test_imported_from_bootstrap(self):
        self.write_memory("user", "Imported fact.")
        led = self.ledger()
        snapshot.bootstrap(led)
        p = service.record_detail(led, "user:" + entry_key("Imported fact."))["provenance"]
        self.assertEqual(p["status"], "imported")
        self.assertTrue(p["imported"])
        self.assertEqual(p["observed"], "import")
        self.assertEqual(p["fallback_reason"], "fallback.imported")

    # 4. external / non-conversation source ------------------------------------
    def test_external_manual_source(self):
        self.write_memory("user", "Hand-written note.")
        led = self.ledger()
        led.add_event(
            kind="memory_added", target_type="user", action="manual_add",
            target_key=entry_key("Hand-written note."), after_text="Hand-written note.",
            source_hint="manual_override",
        )
        p = service.record_detail(led, "user:" + entry_key("Hand-written note."))["provenance"]
        self.assertEqual(p["status"], "external")
        self.assertEqual(p["observed"], "external")
        self.assertEqual(p["fallback_reason"], "fallback.external")

    def test_external_non_agent_skill(self):
        # a community/Hermes skill (not agent-created) comes from a file, not a chat
        self.write_memory("user", "x")
        self.write_skill("productivity", "demo", "---\nname: demo\nauthor: someone\n---\nbody\n")
        led = self.ledger()
        p = service.record_detail(led, "skill:demo")["provenance"]
        self.assertEqual(p["status"], "external")
        self.assertEqual(p["origin_type"], "community")

    # 5. inferred (snapshot diff) ----------------------------------------------
    def test_inferred_from_snapshot_diff(self):
        self.write_memory("user", "Diffed in.")
        led = self.ledger()
        led.add_event(
            kind="memory_added", target_type="user", action="add",
            target_key=entry_key("Diffed in."), after_text="Diffed in.",
            source_hint="snapshot_diff", metadata={"inferred": True},
        )
        p = service.record_detail(led, "user:" + entry_key("Diffed in."))["provenance"]
        self.assertEqual(p["status"], "inferred")
        self.assertEqual(p["fallback_reason"], "fallback.inferred")

    # 6. missing ---------------------------------------------------------------
    def test_missing_when_no_source(self):
        self.write_memory("user", "Orphan entry.")
        led = self.ledger()
        p = service.record_detail(led, "user:" + entry_key("Orphan entry."))["provenance"]
        self.assertEqual(p["status"], "missing")
        self.assertEqual(p["fallback_reason"], "fallback.missing")
        self.assertFalse(p["has_snippet"])

    # 7. list view carries a short status (shallow) ----------------------------
    def test_list_carries_short_status_shallow(self):
        self.write_memory("user", "Orphan entry.")
        led = self.ledger()
        r = next(r for r in service.build_records(led)["records"]
                 if r["target_type"] == "user")
        self.assertEqual(r["provenance"]["status"], "missing")
        # the list is shallow — no heavy session/window resolution
        self.assertNotIn("window", r["provenance"])
        self.assertNotIn("session_title", r["provenance"])

    # detail API returns a complete provenance summary --------------------------
    def test_detail_provenance_summary_complete(self):
        self.write_memory("user", "I like tea.")
        led = self.ledger()
        led.add_event(
            kind="memory_added", target_type="user", action="add",
            target_key=entry_key("I like tea."), after_text="I like tea.",
            source_hint="plugin_hook", source_session_id="s1",
            source_message_window=[{"role": "user", "snippet": "tea?", "timestamp": 1.0}],
        )
        p = service.record_detail(led, "user:" + entry_key("I like tea."))["provenance"]
        for f in ("status", "session_id", "hint", "origin_type",
                  "has_snippet", "has_window", "imported", "observed", "last_traced_at",
                  "fallback_reason", "summary_key", "session_title", "snippet", "window"):
            self.assertIn(f, p)
        self.assertEqual(p["summary_key"], "provenance.summary.exact_match")

    # edited records keep the *original* deposit's provenance -------------------
    def test_edit_preserves_origin_provenance(self):
        # a manual edit should NOT downgrade the source to "external" — the
        # original conversational provenance is what matters; the edit shows up
        # in the version history instead.
        self.write_memory("user", "Original.")
        led = self.ledger()
        Observer(led).on_memory_write(
            "add", "user", "Original.", source_hint="plugin_hook", session_id="s9",
            target_key=entry_key("Original."), capture_window=False,
        )
        # give the origin a traceable window so it reads as exact
        led.conn.execute(
            "UPDATE growth_events SET source_message_window_json=? WHERE after_text='Original.'",
            ('[{"role": "user", "snippet": "tell me", "timestamp": 1.0}]',),
        )
        led.conn.commit()
        service.record_edit(led, "user", entry_key("Original."), "Edited by me.")
        p = service.record_detail(led, "user:" + entry_key("Edited by me."))["provenance"]
        self.assertEqual(p["status"], "exact_match")
