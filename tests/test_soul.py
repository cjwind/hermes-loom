"""SOUL.md management: edit-into-DB + compile-out-to-Hermes.

Loom owns an editable copy of SOUL.md in its DB; saving appends an immutable
version, and compile writes the current DB content out to ~/.hermes/SOUL.md
(backing up any existing file). Content is stored/written verbatim — no
re-serialization — so it round-trips exactly.
"""

from base import LoomTestCase

from hermes_loom import config, soul


class TestSoul(LoomTestCase):
    def _soul_path(self):
        return self.hermes_home / "SOUL.md"

    def test_seed_from_disk_on_first_read(self):
        self._soul_path().write_text("You are Hermes.", encoding="utf-8")
        led = self.ledger()
        cur = soul.current(led)
        self.assertTrue(cur["in_db"])
        self.assertEqual(cur["content"], "You are Hermes.")
        self.assertEqual(cur["source"], "seed")
        self.assertTrue(cur["in_sync"])  # DB seeded straight from disk

    def test_current_when_no_file_and_no_db(self):
        led = self.ledger()
        cur = soul.current(led)
        self.assertFalse(cur["in_db"])
        self.assertEqual(cur["content"], "")
        self.assertFalse(cur["disk"]["exists"])
        self.assertIsNone(cur["in_sync"])

    def test_save_appends_version_and_marks_out_of_sync(self):
        self._soul_path().write_text("v1 on disk", encoding="utf-8")
        led = self.ledger()
        soul.current(led)  # seed v1
        res = soul.save(led, "v2 edited in loom", note="tweak")
        self.assertTrue(res["saved"])
        cur = soul.current(led)
        self.assertEqual(cur["content"], "v2 edited in loom")
        self.assertEqual(cur["source"], "ui_edit")
        # DB now ahead of the still-"v1" disk file
        self.assertFalse(cur["in_sync"])
        self.assertEqual(len(cur["history"]), 2)

    def test_save_identical_is_noop(self):
        led = self.ledger()
        soul.save(led, "same")
        res = soul.save(led, "same")
        self.assertFalse(res["saved"])
        self.assertTrue(res["unchanged"])
        self.assertEqual(len(led.soul_history()), 1)

    def test_compile_writes_file_with_backup(self):
        self._soul_path().write_text("original", encoding="utf-8")
        led = self.ledger()
        soul.current(led)            # seed "original"
        soul.save(led, "new soul")   # DB ahead
        res = soul.compile_to_hermes(led)
        self.assertTrue(res["compiled"])
        self.assertEqual(self._soul_path().read_text(encoding="utf-8"), "new soul")
        # the pre-compile file was backed up under LOOM_HOME/backups
        self.assertTrue(res["backup"])
        self.assertIn("original", (config.file_backup_dir()).glob("SOUL.md.compile-*.bak").__next__().read_text())
        # after compile, DB and disk agree
        self.assertTrue(soul.current(led)["in_sync"])

    def test_compile_without_content_raises(self):
        led = self.ledger()
        with self.assertRaises(ValueError):
            soul.compile_to_hermes(led)

    def test_roundtrip_is_byte_exact(self):
        # tricky content: leading/trailing whitespace, the memory separator, unicode
        tricky = "  你好\n\n§\n line two \t\n"
        led = self.ledger()
        soul.save(led, tricky)
        soul.compile_to_hermes(led)
        self.assertEqual(self._soul_path().read_text(encoding="utf-8"), tricky)
