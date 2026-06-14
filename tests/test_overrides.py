"""Part 10.4 — manual overrides update BOTH the underlying file and the ledger,
and always preserve before/after."""

from base import LoomTestCase
from hermes_loom import overrides
from hermes_loom.memory_parser import parse_entries
from hermes_loom.overrides import OverrideError


SKILL = "---\nname: demo\ndescription: d\n---\n# Demo\noriginal body\n"


class TestMemoryOverrides(LoomTestCase):
    def test_edit_entry_updates_file_and_ledger(self):
        self.write_memory("user", "User likes tea.\n§\nUser uses NixOS.")
        led = self.ledger()
        entries = parse_entries((self.hermes_home / "memories" / "USER.md").read_text())
        key = entries[0]["key"]

        res = overrides.edit_memory_entry(led, "user", key, "User loves green tea.", reason="more precise")

        # underlying file really changed
        new = (self.hermes_home / "memories" / "USER.md").read_text()
        self.assertIn("User loves green tea.", new)
        self.assertNotIn("User likes tea.", new)
        self.assertIn("User uses NixOS.", new)  # other entry untouched

        # ledger recorded override + event with before/after (keyed by new content)
        ov = led.overrides_for_target("user", res["key"])
        self.assertEqual(len(ov), 1)
        self.assertEqual(ov[0]["before_text"], "User likes tea.")
        ev = led.get_event(res["event_id"])
        self.assertEqual(ev["before_text"], "User likes tea.")
        self.assertEqual(ev["after_text"], "User loves green tea.")
        self.assertEqual(ev["source_hint"], "manual_override")
        # a backup file was created
        self.assertTrue(res["backup"])

    def test_delete_entry(self):
        self.write_memory("user", "keep me\n§\ndelete me")
        led = self.ledger()
        entries = parse_entries((self.hermes_home / "memories" / "USER.md").read_text())
        del_key = [e for e in entries if e["text"] == "delete me"][0]["key"]
        overrides.delete_memory_entry(led, "user", del_key)
        new = (self.hermes_home / "memories" / "USER.md").read_text()
        self.assertIn("keep me", new)
        self.assertNotIn("delete me", new)
        self.assertEqual(len(led.query_events(kind="memory_removed")), 1)

    def test_edit_missing_entry_raises(self):
        self.write_memory("user", "something")
        led = self.ledger()
        with self.assertRaises(OverrideError):
            overrides.edit_memory_entry(led, "user", "ebadbadbad", "x")


class TestSkillOverrides(LoomTestCase):
    def test_edit_skill_writes_file(self):
        self.write_skill("productivity", "demo", SKILL)
        led = self.ledger()
        new_content = SKILL.replace("original body", "patched body")
        res = overrides.edit_skill(led, "demo", new_content, reason="fix")
        on_disk = (self.hermes_home / "skills" / "productivity" / "demo" / "SKILL.md").read_text()
        self.assertIn("patched body", on_disk)
        ev = led.get_event(res["event_id"])
        self.assertIn("original body", ev["before_text"])
        self.assertIn("patched body", ev["after_text"])

    def test_disable_skill_soft(self):
        self.write_skill("productivity", "demo", SKILL)
        led = self.ledger()
        overrides.delete_skill(led, "demo", hard=False)
        base = self.hermes_home / "skills" / "productivity" / "demo"
        self.assertFalse((base / "SKILL.md").exists())
        self.assertTrue((base / "SKILL.md.disabled").exists())  # reversible
        self.assertEqual(len(led.query_events(kind="skill_deleted")), 1)
