"""HOLD (暫存): Loom-only entries that are not compiled to any Hermes file."""

from pathlib import Path
from base import LoomTestCase
from hermes_loom import service, overrides, snapshot, compiler


class TestHold(LoomTestCase):
    def _seed(self):
        self.write_memory("memory", "fact A\n§\nfact B")
        led = self.ledger()
        snapshot.bootstrap(led)
        return led

    def _mem_record(self, led, needle):
        return next(r for r in service.build_records(led)["records"]
                   if needle in r["versions"][r["active"]]["value"])

    def test_hold_removes_from_file_and_parks_in_loom(self):
        led = self._seed()
        a = self._mem_record(led, "fact A")
        res = service.record_recategorize(led, a["target_type"], a["target_key"], "hold")
        self.assertEqual(res["to_target_type"], "hold")
        self.assertTrue(res["new_id"].startswith("hold:"))
        # removed from MEMORY.md, B still there
        mem = (self.hermes_home / "memories" / "MEMORY.md").read_text()
        self.assertNotIn("fact A", mem)
        self.assertIn("fact B", mem)
        # shows as a hold record
        held = [r for r in service.build_records(led)["records"] if r["target_type"] == "hold"]
        self.assertEqual(len(held), 1)
        self.assertEqual(held[0]["cat"], "hold")
        self.assertEqual(held[0]["versions"][0]["value"], "fact A")

    def test_held_not_compiled(self):
        led = self._seed()
        a = self._mem_record(led, "fact A")
        service.record_recategorize(led, a["target_type"], a["target_key"], "hold")
        out = Path(self.tmp.name) / "exp"
        compiler.compile_to_dir(led, out)
        compiled = (out / "memories" / "MEMORY.md").read_text()
        self.assertIn("fact B", compiled)
        self.assertNotIn("fact A", compiled)        # held entry must not leak
        self.assertFalse((out / "memories" / "USER.md").exists())

    def test_unhold_back_to_file(self):
        led = self._seed()
        a = self._mem_record(led, "fact A")
        service.record_recategorize(led, a["target_type"], a["target_key"], "hold")
        held = next(r for r in service.build_records(led)["records"] if r["target_type"] == "hold")
        service.record_recategorize(led, "hold", held["target_key"], "pref")
        self.assertIn("fact A", (self.hermes_home / "memories" / "USER.md").read_text())
        self.assertEqual([r for r in service.build_records(led)["records"] if r["target_type"] == "hold"], [])

    def test_hold_to_hold_rejected(self):
        led = self._seed()
        a = self._mem_record(led, "fact A")
        service.record_recategorize(led, a["target_type"], a["target_key"], "hold")
        held = next(r for r in service.build_records(led)["records"] if r["target_type"] == "hold")
        with self.assertRaises(overrides.OverrideError):
            service.record_recategorize(led, "hold", held["target_key"], "hold")

    def test_edit_and_delete_held(self):
        led = self._seed()
        a = self._mem_record(led, "fact A")
        service.record_recategorize(led, a["target_type"], a["target_key"], "hold")
        held = next(r for r in service.build_records(led)["records"] if r["target_type"] == "hold")
        # edit
        service.record_edit(led, "hold", held["target_key"], "fact A (revised)")
        held2 = next(r for r in service.build_records(led)["records"] if r["target_type"] == "hold")
        self.assertEqual(held2["versions"][0]["value"], "fact A (revised)")
        # delete + re-hold (undo path)
        text = held2["versions"][0]["value"]
        service.record_delete(led, "hold", held2["target_key"])
        self.assertEqual([r for r in service.build_records(led)["records"] if r["target_type"] == "hold"], [])
        overrides.rehold_entry(led, text)
        self.assertEqual(len([r for r in service.build_records(led)["records"] if r["target_type"] == "hold"]), 1)

    def test_hold_category_exposed(self):
        led = self.ledger()
        cats = {c["k"] for c in service.build_records(led)["cats"]}
        self.assertEqual(cats, {"memory", "skill", "pref", "hold"})
