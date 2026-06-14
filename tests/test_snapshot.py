"""Part 10.3 — bootstrap import + snapshot-diff fallback produce events."""

from base import LoomTestCase
from hermes_loom import snapshot


SKILL = """---
name: demo
description: a demo skill
tags: [a, b]
---
# Demo
body
"""


class TestBootstrap(LoomTestCase):
    def test_bootstrap_imports_memory_and_skills(self):
        self.write_memory("user", "User likes tea.\n§\nUser uses NixOS.")
        self.write_skill("productivity", "demo", SKILL)
        led = self.ledger()

        res = snapshot.bootstrap(led)
        self.assertFalse(res["skipped"])

        mem = led.query_events(kind="memory_snapshot_imported")
        sk = led.query_events(kind="skill_snapshot_imported")
        self.assertEqual(len(mem), 1)
        self.assertEqual(len(sk), 1)
        # historical flag distinguishes imports from runtime-observed events
        self.assertTrue(mem[0]["metadata"]["historical"])

    def test_bootstrap_is_idempotent(self):
        self.write_memory("user", "fact")
        led = self.ledger()
        snapshot.bootstrap(led)
        again = snapshot.bootstrap(led)
        self.assertTrue(again["skipped"])


class TestReconcile(LoomTestCase):
    def test_memory_diff_detects_add(self):
        self.write_memory("user", "fact one")
        led = self.ledger()
        snapshot.bootstrap(led)

        # simulate Hermes appending an entry WITHOUT a hook firing
        self.write_memory("user", "fact one\n§\nfact two")
        new_ids = snapshot.reconcile_memory(led, "user")
        self.assertEqual(len(new_ids), 1)
        ev = led.get_event(new_ids[0])
        self.assertEqual(ev["kind"], "memory_added")
        self.assertEqual(ev["source_hint"], "snapshot_diff")
        self.assertTrue(ev["metadata"]["inferred"])
        self.assertIn("fact two", ev["after_text"])

    def test_memory_diff_detects_replace(self):
        self.write_memory("user", "old fact")
        led = self.ledger()
        snapshot.bootstrap(led)
        self.write_memory("user", "new fact")
        ids = snapshot.reconcile_memory(led, "user")
        ev = led.get_event(ids[0])
        self.assertEqual(ev["kind"], "memory_replaced")
        self.assertEqual(ev["before_text"], "old fact")
        self.assertEqual(ev["after_text"], "new fact")

    def test_skill_diff_detects_edit(self):
        path = self.write_skill("productivity", "demo", SKILL)
        led = self.ledger()
        snapshot.bootstrap(led)
        path.write_text(SKILL + "\nmore content", encoding="utf-8")
        ids = snapshot.reconcile_skills(led)
        self.assertEqual(len(ids), 1)
        self.assertEqual(led.get_event(ids[0])["kind"], "skill_edited")

    def test_no_change_no_event(self):
        self.write_memory("user", "stable")
        led = self.ledger()
        snapshot.bootstrap(led)
        self.assertEqual(snapshot.reconcile_memory(led, "user"), [])
