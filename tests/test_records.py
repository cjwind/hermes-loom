"""Inspector records aggregation + tuning (annotate/reclassify/pin/add)."""

from base import LoomTestCase
from hermes_loom import service, overrides
from hermes_loom.observer import Observer


class TestRecords(LoomTestCase):
    def _seed(self):
        self.write_memory("user", "User likes tea.\n§\nUser uses NixOS.")
        led = self.ledger()
        obs = Observer(led)
        # create matching auto-origin events so provenance/versions populate
        obs.on_memory_write("add", "user", "User likes tea.", capture_window=False)
        obs.on_memory_write("add", "user", "User uses NixOS.", capture_window=False)
        return led

    def test_only_three_categories(self):
        led = self._seed()
        out = service.build_records(led)
        keys = sorted(c["k"] for c in out["cats"])
        self.assertEqual(keys, ["memory", "pref", "skill"])

    def test_legacy_category_coerced(self):
        led = self._seed()
        r = service.build_records(led)["records"][0]
        # simulate a stale reclassify to a removed category
        led.upsert_record_state(r["target_type"], r["target_key"], cat="fact")
        d = service.record_detail(led, r["id"])
        self.assertIn(d["cat"], ("memory", "pref", "skill"))

    def test_build_records_from_live_entries(self):
        led = self._seed()
        out = service.build_records(led)
        users = [r for r in out["records"] if r["target_type"] == "user"]
        self.assertEqual(len(users), 2)
        r = next(r for r in users if "tea" in r["versions"][r["active"]]["value"])
        self.assertEqual(r["cat"], "pref")               # user store default
        self.assertEqual(r["versions"][0]["kind"], "auto")
        self.assertEqual(r["conf"], 3)                   # plugin_hook origin

    def test_record_detail_roundtrip(self):
        led = self._seed()
        rid = service.build_records(led)["records"][0]["id"]
        d = service.record_detail(led, rid)
        self.assertIsNotNone(d)
        self.assertEqual(d["id"], rid)

    def test_edit_creates_human_version(self):
        led = self._seed()
        out = service.build_records(led)
        r = next(r for r in out["records"] if "tea" in r["versions"][r["active"]]["value"])
        service.record_edit(led, r["target_type"], r["target_key"], "User loves oolong tea.")
        # rebuild — the edited entry now has an auto v1 + human v2
        out2 = service.build_records(led)
        r2 = next(r for r in out2["records"] if "oolong" in r["versions"][r["active"]]["value"])
        self.assertEqual(len(r2["versions"]), 2)
        self.assertEqual(r2["versions"][1]["kind"], "human")
        self.assertEqual(r2["active"], 1)
        # underlying file really changed
        self.assertIn("oolong", (self.hermes_home / "memories" / "USER.md").read_text())

    def test_annotate_reclassify_pin(self):
        led = self._seed()
        r = service.build_records(led)["records"][0]
        tt, tk = r["target_type"], r["target_key"]
        overrides.annotate_record(led, tt, tk, "只在工作情境適用")
        overrides.reclassify_record(led, tt, tk, "memory", from_cat=r["cat"])
        overrides.set_pin(led, tt, tk, True)
        d = service.record_detail(led, f"{tt}:{tk}")
        self.assertEqual(d["annotation"]["text"], "只在工作情境適用")
        self.assertEqual(d["cat"], "memory")
        self.assertTrue(d["pinned"])
        self.assertEqual(d["reclassified"]["to"], "memory")

    def test_add_entry_for_delete_undo(self):
        led = self._seed()
        res = overrides.add_memory_entry(led, "user", "User drinks coffee too.")
        self.assertIn("User drinks coffee too.", (self.hermes_home / "memories" / "USER.md").read_text())
        self.assertTrue(res["key"])
