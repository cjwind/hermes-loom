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

    def test_categories(self):
        led = self._seed()
        out = service.build_records(led)
        keys = sorted(c["k"] for c in out["cats"])
        self.assertEqual(keys, ["hold", "memory", "pref", "skill"])

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

    def test_records_sorted_by_time_desc(self):
        self.write_memory("user", "older entry\n§\nnewer entry")
        led = self.ledger()
        obs = Observer(led)
        obs.on_memory_write("add", "user", "older entry", timestamp=1000.0, capture_window=False)
        obs.on_memory_write("add", "user", "newer entry", timestamp=2000.0, capture_window=False)
        out = service.build_records(led)
        users = [r for r in out["records"] if r["target_type"] == "user"]
        self.assertEqual(users[0]["versions"][users[0]["active"]]["value"], "newer entry")
        self.assertEqual(users[1]["versions"][users[1]["active"]]["value"], "older entry")
        # overall list is monotonically non-increasing by ts
        ts = [r.get("ts") or 0 for r in out["records"]]
        self.assertEqual(ts, sorted(ts, reverse=True))

    def test_edited_record_floats_up(self):
        self.write_memory("user", "a\n§\nb")
        led = self.ledger()
        obs = Observer(led)
        obs.on_memory_write("add", "user", "a", timestamp=5000.0, capture_window=False)
        obs.on_memory_write("add", "user", "b", timestamp=9000.0, capture_window=False)
        # edit the older one ("a") → its ts becomes "now" (huge) → floats to top
        out = service.build_records(led)
        a = next(r for r in out["records"] if r["versions"][r["active"]]["value"] == "a")
        service.record_edit(led, a["target_type"], a["target_key"], "a-edited")
        out2 = service.build_records(led)
        self.assertEqual(out2["records"][0]["versions"][out2["records"][0]["active"]]["value"], "a-edited")

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

    def test_annotate_and_pin(self):
        led = self._seed()
        r = service.build_records(led)["records"][0]
        tt, tk = r["target_type"], r["target_key"]
        overrides.annotate_record(led, tt, tk, "只在工作情境適用")
        overrides.set_pin(led, tt, tk, True)
        d = service.record_detail(led, f"{tt}:{tk}")
        self.assertEqual(d["annotation"]["text"], "只在工作情境適用")
        self.assertTrue(d["pinned"])

    def test_recategorize_moves_entry_between_files(self):
        self.write_memory("memory", "remember tea")
        self.write_memory("user", "prefers dark mode")
        led = self.ledger()
        recs = service.build_records(led)["records"]
        mem = next(r for r in recs if r["target_type"] == "memory")
        res = service.record_recategorize(led, mem["target_type"], mem["target_key"], "pref")
        # physically moved: gone from MEMORY.md, present in USER.md
        self.assertNotIn("remember tea", (self.hermes_home / "memories" / "MEMORY.md").read_text())
        user_txt = (self.hermes_home / "memories" / "USER.md").read_text()
        self.assertIn("remember tea", user_txt)
        self.assertIn("prefers dark mode", user_txt)  # existing entry kept
        self.assertEqual(res["to_target_type"], "user")
        self.assertTrue(res["new_id"].startswith("user:"))
        self.assertTrue(res["backups"])

    def test_recategorize_then_compiles_to_new_file(self):
        self.write_memory("memory", "remember tea")
        led = self.ledger()
        mem = next(r for r in service.build_records(led)["records"] if r["target_type"] == "memory")
        service.record_recategorize(led, "memory", mem["target_key"], "pref")
        # the moved entry now shows up as a 偏好 (user) record
        recs2 = service.build_records(led)["records"]
        moved = next(r for r in recs2 if "remember tea" in r["versions"][r["active"]]["value"])
        self.assertEqual(moved["target_type"], "user")
        self.assertEqual(moved["cat"], "pref")

    def test_recategorize_skill_rejected(self):
        self.write_skill("productivity", "demo", "---\nname: demo\n---\nbody\n")
        led = self.ledger()
        with self.assertRaises(overrides.OverrideError):
            service.record_recategorize(led, "skill", "demo", "memory")

    def test_recategorize_same_category_rejected(self):
        self.write_memory("memory", "x")
        led = self.ledger()
        mem = next(r for r in service.build_records(led)["records"] if r["target_type"] == "memory")
        with self.assertRaises(overrides.OverrideError):
            service.record_recategorize(led, "memory", mem["target_key"], "memory")

    def test_skill_detail_has_full_content_and_edit_rewrites_file(self):
        self.write_memory("user", "x")
        skill_md = self.write_skill("productivity", "demo",
                                    "---\nname: demo\ncreated_by: agent\n---\n# Demo\noriginal body\n")
        led = self.ledger()
        d = service.record_detail(led, "skill:demo")
        self.assertIn("skill_content", d)
        self.assertIn("original body", d["skill_content"])
        self.assertTrue(d["is_agent_created"])
        new = d["skill_content"].replace("original body", "PATCHED body")
        service.record_edit(led, "skill", "demo", new)
        self.assertIn("PATCHED body", skill_md.read_text())

    def test_add_entry_for_delete_undo(self):
        led = self._seed()
        res = overrides.add_memory_entry(led, "user", "User drinks coffee too.")
        self.assertIn("User drinks coffee too.", (self.hermes_home / "memories" / "USER.md").read_text())
        self.assertTrue(res["key"])
