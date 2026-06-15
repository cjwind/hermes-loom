"""Regression: a live (plugin_hook) write must keep its precise provenance
across a restart.

Bug: the plugin recorded a memory/skill change as a `plugin_hook` event but did
NOT advance the stored snapshot. On the next `on_session_start`, `reconcile`
diffed the (now-stale) snapshot against the live file, re-discovered the same
change, and emitted a `snapshot_diff` event. Because `_origin_event` returns the
*most recent* event matching the content, the newer snapshot_diff overrode the
plugin_hook origin — so "即時由 plugin 觀測到" silently became "由快照比對推測"
after a restart.

Fix: the live write path advances the snapshot, so reconcile finds no diff.
"""

from base import LoomTestCase
from hermes_loom import plugin, snapshot, service


class TestProvenanceStableAcrossRestart(LoomTestCase):
    def _plugin_with_ledger(self):
        p = plugin.LoomPlugin()
        self.addCleanup(p.ledger.close)
        return p, p.ledger

    # -- memory --------------------------------------------------------------
    def test_memory_plugin_hook_survives_reconcile(self):
        # Baseline: one existing entry, snapshotted at bootstrap.
        self.write_memory("user", "Existing fact.")
        p, led = self._plugin_with_ledger()
        snapshot.bootstrap(led)

        # Hermes adds an entry live: the file is updated on disk first, THEN
        # post_tool_call fires — exactly the real ordering.
        self.write_memory("user", "Existing fact.\n§\nUser loves matcha.")
        p.on_post_tool_call(
            tool_name="memory",
            args={"action": "add", "target": "user", "content": "User loves matcha."},
            result={"success": True}, session_id="sess-live", tool_call_id="c1")

        # The live write advanced the snapshot to the file's new state.
        snap = led.latest_memory_snapshot("user")
        self.assertIn("User loves matcha.", snap["content"])

        # Simulate a restart: reconcile must find nothing new (no snapshot_diff).
        self.assertEqual(snapshot.reconcile_memory(led, "user"), [])

        # Exactly one event carries the new entry, and it stays plugin_hook.
        evs = [e for e in led.query_events(target_type="user")
               if e["after_text"] == "User loves matcha."]
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["source_hint"], "plugin_hook")

        # And the user-facing provenance resolves to the live origin.
        origin = service._origin_event(led, "user", "User loves matcha.")
        self.assertEqual(origin["source_hint"], "plugin_hook")

    # -- skill ---------------------------------------------------------------
    def test_skill_plugin_hook_survives_reconcile(self):
        self.write_skill("memory", "demo", "---\nname: demo\n---\nv1 body")
        p, led = self._plugin_with_ledger()
        snapshot.bootstrap(led)

        # Live edit: file updated first, then the hook fires.
        new_md = "---\nname: demo\n---\nv2 body"
        self.write_skill("memory", "demo", new_md)
        p.on_post_tool_call(
            tool_name="skill_manage",
            args={"action": "edit", "skill_name": "demo", "skill_md": new_md},
            result={"success": True}, session_id="s", tool_call_id="c")

        # Snapshot advanced -> reconcile emits nothing.
        self.assertEqual(snapshot.reconcile_skills(led), [])

        edits = [e for e in led.query_events(target_type="skill")
                 if e["kind"] == "skill_edited"]
        self.assertEqual(len(edits), 1)
        self.assertEqual(edits[0]["source_hint"], "plugin_hook")

    # -- guard: the fix doesn't suppress genuine offline changes -------------
    def test_unhooked_change_still_inferred(self):
        """A change made WITHOUT a hook (e.g. predates install / edited offline)
        must still be caught by reconcile as snapshot_diff — the fix only covers
        changes the plugin actually observed."""
        self.write_memory("user", "Existing fact.")
        p, led = self._plugin_with_ledger()
        snapshot.bootstrap(led)

        # File changes but no hook fires.
        self.write_memory("user", "Existing fact.\n§\nAdded behind Loom's back.")
        new_ids = snapshot.reconcile_memory(led, "user")
        self.assertEqual(len(new_ids), 1)
        ev = led.query_events(kind="memory_added")[0]
        self.assertEqual(ev["source_hint"], "snapshot_diff")
