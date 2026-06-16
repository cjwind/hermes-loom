"""Drift detection: live Hermes files vs Loom's latest snapshots."""

from base import LoomTestCase

from hermes_loom import drift, snapshot


class DriftTest(LoomTestCase):
    # -- memory / user --------------------------------------------------------

    def test_in_sync_after_bootstrap(self):
        self.write_memory("user", "偏好繁體中文\n§\n住在台灣\n")
        led = self.ledger()
        snapshot.bootstrap(led)
        s = drift.summary(led)
        self.assertEqual(s["overall"], "in_sync")
        self.assertEqual(s["user"]["status"], "in_sync")
        self.assertEqual(s["drift_count"], 0)

    def test_drifted_entry_change_is_counted_as_changed(self):
        self.write_memory("user", "住在台灣\n§\n喜歡美式咖啡\n")
        led = self.ledger()
        snapshot.bootstrap(led)
        # edit one entry in place — must read as 1 changed, not remove+add
        self.write_memory("user", "住在台北\n§\n喜歡美式咖啡\n")
        s = drift.summary(led)
        self.assertEqual(s["overall"], "drifted")
        self.assertEqual(s["user"]["status"], "drifted")
        self.assertEqual(s["user"]["summary"], {"added": 0, "removed": 0, "changed": 1})
        self.assertEqual(s["drift_count"], 1)

    def test_drifted_clean_add_and_remove(self):
        # a clean insert (C appended) and a clean delete (B removed between A,D)
        self.write_memory("memory", "A\n§\nB\n§\nD\n")
        led = self.ledger()
        snapshot.bootstrap(led)
        self.write_memory("memory", "A\n§\nD\n§\nC\n")  # B deleted, C appended
        s = drift.summary(led)
        self.assertEqual(s["memory"]["status"], "drifted")
        self.assertEqual(s["memory"]["summary"], {"added": 1, "removed": 1, "changed": 0})

    def test_replace_region_splits_into_changed_plus_add(self):
        # SequenceMatcher pairs a 1→2 replace as 1 changed + 1 net add (no max-inflation)
        self.write_memory("memory", "A\n§\nB\n")
        led = self.ledger()
        snapshot.bootstrap(led)
        self.write_memory("memory", "A\n§\nC\n§\nD\n")  # B → C,D
        s = drift.summary(led)
        self.assertEqual(s["memory"]["summary"], {"added": 1, "removed": 0, "changed": 1})

    def test_missing_file(self):
        self.write_memory("user", "X\n")
        led = self.ledger()
        snapshot.bootstrap(led)
        (self.hermes_home / "memories" / "USER.md").unlink()
        s = drift.summary(led)
        self.assertEqual(s["user"]["status"], "missing_file")
        self.assertEqual(s["overall"], "drifted")

    def test_no_baseline_when_absent_both_sides(self):
        led = self.ledger()
        snapshot.bootstrap(led)  # no MEMORY.md on disk
        s = drift.summary(led)
        self.assertEqual(s["memory"]["status"], "no_baseline")
        self.assertEqual(s["overall"], "in_sync")  # nothing to drift from

    # -- skills ---------------------------------------------------------------

    def test_untracked_skill(self):
        led = self.ledger()
        snapshot.bootstrap(led)  # no skills yet
        self.write_skill("writing", "haiku", "---\nname: haiku\n---\nbody\n")
        s = drift.summary(led)
        item = next(i for i in s["skills"]["items"] if i["name"] == "haiku")
        self.assertEqual(item["status"], "untracked")
        self.assertEqual(s["skills"]["status"], "drifted")

    def test_skill_drift_and_detail_diff(self):
        self.write_skill("writing", "haiku", "---\nname: haiku\n---\nfirst line\n")
        led = self.ledger()
        snapshot.bootstrap(led)
        self.write_skill("writing", "haiku", "---\nname: haiku\n---\nsecond line\n")
        s = drift.summary(led)
        item = next(i for i in s["skills"]["items"] if i["name"] == "haiku")
        self.assertEqual(item["status"], "drifted")

        d = drift.detail(led, "skill:haiku")
        joined = "\n".join(d["diff"])
        self.assertIn("-first line", joined)
        self.assertIn("+second line", joined)

    def test_deleted_skill_pending_then_acknowledged(self):
        self.write_skill("writing", "haiku", "---\nname: haiku\n---\nbody\n")
        led = self.ledger()
        snapshot.bootstrap(led)
        # delete the file: pending drift until reconcile acknowledges it
        (self.hermes_home / "skills" / "writing" / "haiku" / "SKILL.md").unlink()
        s1 = drift.summary(led)
        item = next(i for i in s1["skills"]["items"] if i["name"] == "haiku")
        self.assertEqual(item["status"], "missing_file")

        snapshot.reconcile_skills(led)  # emits skill_deleted
        s2 = drift.summary(led)
        self.assertFalse(any(i["name"] == "haiku" for i in s2["skills"]["items"]))
        self.assertEqual(s2["skills"]["status"], "in_sync")

    # -- detail payload -------------------------------------------------------

    def test_memory_detail_unified_diff(self):
        self.write_memory("user", "住在台灣\n")
        led = self.ledger()
        snapshot.bootstrap(led)
        self.write_memory("user", "住在台北\n")
        d = drift.detail(led, "user")
        joined = "\n".join(d["diff"])
        self.assertIn("-住在台灣", joined)
        self.assertIn("+住在台北", joined)
        self.assertEqual(d["summary"], {"added": 0, "removed": 0, "changed": 1})

    def test_detail_unknown_target(self):
        led = self.ledger()
        self.assertIsNone(drift.detail(led, "nope"))
