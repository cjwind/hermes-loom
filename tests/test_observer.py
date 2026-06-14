"""Part 10.1, 10.2, 10.7, 10.8 — observer writes events with before/after; never crashes."""

from base import LoomTestCase
from hermes_loom.observer import Observer


class TestMemoryObservation(LoomTestCase):
    def test_memory_add_replace_remove_write_events(self):
        led = self.ledger()
        obs = Observer(led)
        obs.on_memory_write("add", "user", "User likes tea.", capture_window=False)
        obs.on_memory_write("replace", "user", "User loves tea.",
                            before_text="User likes tea.", capture_window=False)
        obs.on_memory_write("remove", "memory", None,
                            before_text="old fact", capture_window=False)

        evs = led.query_events()
        kinds = sorted(e["kind"] for e in evs)
        self.assertEqual(kinds, ["memory_added", "memory_removed", "memory_replaced"])

    def test_before_after_preserved(self):
        led = self.ledger()
        Observer(led).on_memory_write(
            "replace", "user", "new text", before_text="old text", capture_window=False)
        e = led.query_events(kind="memory_replaced")[0]
        self.assertEqual(e["before_text"], "old text")
        self.assertEqual(e["after_text"], "new text")

    def test_target_user_vs_memory(self):
        led = self.ledger()
        obs = Observer(led)
        obs.on_memory_write("add", "user", "x", capture_window=False)
        obs.on_memory_write("add", "memory", "y", capture_window=False)
        self.assertEqual(len(led.query_events(target_type="user")), 1)
        self.assertEqual(len(led.query_events(target_type="memory")), 1)


class TestSkillObservation(LoomTestCase):
    def test_skill_create_patch_edit_delete(self):
        led = self.ledger()
        obs = Observer(led)
        for action in ("create", "patch", "edit", "delete"):
            obs.on_skill_write(action, "demo-skill", content="body-" + action, capture_window=False)
        kinds = sorted(e["kind"] for e in led.query_events(target_type="skill"))
        self.assertEqual(kinds, ["skill_created", "skill_deleted", "skill_edited", "skill_patched"])


class TestObserverRobustness(LoomTestCase):
    def test_observer_never_raises(self):
        """Part 10.8 — a broken ledger must not propagate out of the observer."""
        class BoomLedger:
            def add_event(self, **kw):
                raise RuntimeError("db exploded")
        obs = Observer(BoomLedger())
        # Should swallow the error and return None, not raise.
        result = obs.on_memory_write("add", "user", "x", capture_window=False)
        self.assertIsNone(result)
        result2 = obs.on_skill_write("create", "s", capture_window=False)
        self.assertIsNone(result2)
