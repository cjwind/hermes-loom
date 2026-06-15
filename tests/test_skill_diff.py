"""Skill version history powers the per-skill diff viewer.

`record_detail` for a skill must expose a `skill_versions` timeline (full
SKILL.md content per version, oldest→newest, provenance-labelled) built from the
skill_snapshots table, so the UI can line-diff any two versions.
"""

from base import LoomTestCase
from hermes_loom import plugin, snapshot, overrides, service


class TestSkillVersionHistory(LoomTestCase):
    def _plugin(self):
        p = plugin.LoomPlugin()
        self.addCleanup(p.ledger.close)
        return p, p.ledger

    def _fire_skill_edit(self, p, md):
        p.on_post_tool_call(
            tool_name="skill_manage",
            args={"action": "edit", "skill_name": "demo", "skill_md": md},
            result={"success": True}, session_id="s", tool_call_id="c")

    def test_snapshots_listed_oldest_first(self):
        self.write_skill("memory", "demo", "v1")
        _, led = self._plugin()
        snapshot.bootstrap(led)
        self.write_skill("memory", "demo", "v2")
        snapshot.capture_skill_snapshot(led, "demo")
        snaps = led.list_skill_snapshots("demo")
        self.assertEqual([s["content"] for s in snaps], ["v1", "v2"])

    def test_history_labels_each_version_by_provenance(self):
        # v1: existing at install (bootstrap → historical/auto)
        self.write_skill("memory", "demo", "---\nname: demo\n---\nv1")
        p, led = self._plugin()
        snapshot.bootstrap(led)

        # v2: Hermes edits it live (plugin_hook → auto)
        v2 = "---\nname: demo\n---\nv2 by hermes"
        self.write_skill("memory", "demo", v2)
        self._fire_skill_edit(p, v2)

        # v3: the user edits it in Loom (manual_override → human)
        v3 = "---\nname: demo\n---\nv3 by you"
        overrides.edit_skill(led, "demo", v3)

        hist = service._skill_version_history(led, "demo", v3)

        self.assertEqual([h["value"] for h in hist],
                         ["---\nname: demo\n---\nv1", v2, v3])
        self.assertEqual([h["v"] for h in hist], ["v1", "v2", "v3"])
        self.assertEqual([h["kind"] for h in hist], ["auto", "auto", "human"])
        # `who` is now an i18n key resolved by the UI, not localized text.
        self.assertEqual(hist[-1]["who"], "who.you")

    def test_current_file_appended_when_not_snapshotted(self):
        """An offline change not yet reconciled still shows as the newest version."""
        self.write_skill("memory", "demo", "snapped")
        _, led = self._plugin()
        snapshot.bootstrap(led)
        hist = service._skill_version_history(led, "demo", "edited offline")
        self.assertEqual(hist[-1]["value"], "edited offline")
        self.assertEqual(hist[-1]["who"], "who.currentFile")

    def test_record_detail_exposes_skill_versions(self):
        self.write_skill("memory", "demo", "---\nname: demo\n---\nv1")
        p, led = self._plugin()
        snapshot.bootstrap(led)
        v2 = "---\nname: demo\n---\nv2"
        self.write_skill("memory", "demo", v2)
        self._fire_skill_edit(p, v2)

        rec = service.record_detail(led, "skill:demo")
        self.assertIsNotNone(rec)
        self.assertIn("skill_versions", rec)
        self.assertEqual(len(rec["skill_versions"]), 2)
        self.assertEqual(rec["skill_versions"][-1]["value"], v2)
