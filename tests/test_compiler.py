"""Compile MEMORY.md / USER.md / SKILL.md back out of the ledger snapshots."""

from pathlib import Path
from base import LoomTestCase
from hermes_loom import compiler, snapshot, overrides


SKILL = "---\nname: demo\nauthor: Hermes Agent\n---\n# Demo\nbody here\n"


class TestCompiler(LoomTestCase):
    def _seed(self):
        self.write_memory("memory", "# MEMORY\nremember X")
        self.write_memory("user", "fact one\n§\nfact two")
        self.write_skill("productivity", "demo", SKILL)
        led = self.ledger()
        snapshot.bootstrap(led)
        return led

    def test_compile_to_dir_roundtrips(self):
        led = self._seed()
        out = Path(self.tmp.name) / "export"
        res = compiler.compile_to_dir(led, out)
        self.assertEqual(res["files"], 3)
        self.assertEqual(
            (out / "memories" / "USER.md").read_text(),
            (self.hermes_home / "memories" / "USER.md").read_text())
        self.assertEqual(
            (out / "memories" / "MEMORY.md").read_text(),
            (self.hermes_home / "memories" / "MEMORY.md").read_text())
        self.assertEqual(
            (out / "skills" / "productivity" / "demo" / "SKILL.md").read_text(), SKILL)

    def test_compile_to_dir_never_touches_hermes(self):
        led = self._seed()
        before = (self.hermes_home / "memories" / "USER.md").read_text()
        compiler.compile_to_dir(led, Path(self.tmp.name) / "export")
        self.assertEqual((self.hermes_home / "memories" / "USER.md").read_text(), before)

    def test_compile_in_place_overwrites_with_backup(self):
        led = self._seed()
        # corrupt the live file, then rebuild from the ledger
        (self.hermes_home / "memories" / "USER.md").write_text("CORRUPTED", encoding="utf-8")
        res = compiler.compile_in_place(led)
        self.assertEqual((self.hermes_home / "memories" / "USER.md").read_text(),
                         "fact one\n§\nfact two")
        self.assertTrue(res["backups"])  # the corrupted file was backed up first

    def test_as_of_picks_historical_snapshot(self):
        self.write_memory("user", "v1 content")
        led = self.ledger()
        led.add_memory_snapshot("user", "v1 content", "h1", captured_at=1000.0)
        led.add_memory_snapshot("user", "v2 content", "h2", captured_at=2000.0)
        # latest
        self.assertEqual(compiler.collect(led)["memory"]["user"]["content"], "v2 content")
        # as-of between the two → older snapshot
        data = compiler.collect(led, as_of=1500.0)
        self.assertEqual(data["memory"]["user"]["content"], "v1 content")

    def test_missing_reported_when_no_snapshot(self):
        led = self.ledger()  # empty ledger, no snapshots
        res = compiler.compile_to_dir(led, Path(self.tmp.name) / "e")
        self.assertEqual(res["files"], 0)
        self.assertIn("USER.md", res["missing"])

    def test_cli_compile_auto_syncs_to_latest(self):
        from hermes_loom import cli, snapshot
        self.write_memory("user", "old fact")
        # bootstrap once, then Hermes changes the file without Loom observing
        led = self.ledger(); snapshot.bootstrap(led)
        self.write_memory("user", "old fact\n§\nbrand new fact")
        out = Path(self.tmp.name) / "auto"
        cli.main(["compile", "--out", str(out)])           # default → auto-sync
        self.assertIn("brand new fact", (out / "memories" / "USER.md").read_text())

    def test_cli_compile_no_sync_is_stale(self):
        from hermes_loom import cli, snapshot
        self.write_memory("user", "old fact")
        led = self.ledger(); snapshot.bootstrap(led)
        self.write_memory("user", "old fact\n§\nbrand new fact")
        out = Path(self.tmp.name) / "nosync"
        cli.main(["compile", "--out", str(out), "--no-sync"])
        self.assertNotIn("brand new fact", (out / "memories" / "USER.md").read_text())

    def test_parse_as_of(self):
        self.assertIsNone(compiler.parse_as_of(None))
        self.assertEqual(compiler.parse_as_of("1500"), 1500.0)
        self.assertIsInstance(compiler.parse_as_of("2026-06-14"), float)
        self.assertIsInstance(compiler.parse_as_of("2026-06-14 12:00"), float)
        with self.assertRaises(ValueError):
            compiler.parse_as_of("not-a-date")
