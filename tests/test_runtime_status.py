"""Compile / Drift status — the runtime-targets control-plane read model.

Covers: compile records a fingerprint + time; an unchanged file reads in_sync; an
externally-changed file reads drifted; a never-compiled target reports clearly; the
status payload has the documented fields; and a failed write reports compile_failed.
"""

from base import LoomTestCase
from hermes_loom import compiler, runtime, service, snapshot, soul
from hermes_loom.memory_parser import entry_key


class TestRuntimeStatus(LoomTestCase):
    def _seed_and_compile(self):
        """Bootstrap snapshots from live files, then compile out to runtime."""
        self.write_memory("memory", "Assistant remembers tea.")
        self.write_memory("user", "User likes tea.")
        led = self.ledger()
        snapshot.bootstrap(led)
        runtime.compile_all(led)
        return led

    # 1. compile records fingerprint + time ------------------------------------
    def test_compile_records_fingerprint_and_time(self):
        led = self._seed_and_compile()
        ev = led.latest_successful_compile("memory")
        self.assertIsNotNone(ev)
        self.assertEqual(ev["status"], "compiled")
        self.assertTrue(ev["fingerprint"])
        self.assertTrue(ev["timestamp"])
        # the recorded fingerprint matches the file Loom wrote
        st = runtime._target_status(led, "memory")
        self.assertEqual(st["last_compiled_fingerprint"], st["current_runtime_fingerprint"])

    # 2. unchanged runtime file → in_sync --------------------------------------
    def test_in_sync_when_unchanged(self):
        led = self._seed_and_compile()
        st = runtime._target_status(led, "user")
        self.assertEqual(st["compile_status"], "compiled")
        self.assertEqual(st["drift_status"], "in_sync")

    # 3. externally changed runtime file → drifted -----------------------------
    def test_drifted_when_runtime_changes(self):
        led = self._seed_and_compile()
        # simulate Hermes writing to the file after Loom compiled it
        self.write_memory("user", "User likes tea.\n§\nUser also likes coffee.")
        st = runtime._target_status(led, "user")
        self.assertEqual(st["drift_status"], "drifted")
        self.assertNotEqual(st["last_compiled_fingerprint"], st["current_runtime_fingerprint"])
        # the new entry is unmanaged (Hermes wrote it, Loom didn't compile it)
        self.assertGreaterEqual(st["unmanaged_item_count"], 1)

    # 4. never compiled → explicit status --------------------------------------
    def test_never_compiled_target(self):
        self.write_memory("memory", "Something Hermes grew.")
        led = self.ledger()
        snapshot.bootstrap(led)            # snapshot exists, but no compile yet
        st = runtime._target_status(led, "memory")
        self.assertEqual(st["compile_status"], "never_compiled")
        self.assertEqual(st["drift_status"], "unknown")
        self.assertIsNone(st["last_compiled_fingerprint"])
        # runtime content that Loom never compiled counts as unmanaged
        self.assertGreaterEqual(st["unmanaged_item_count"], 1)

    # 5. runtime-status API payload has the documented fields -------------------
    def test_runtime_status_payload_fields(self):
        led = self._seed_and_compile()
        payload = runtime.runtime_status(led)
        self.assertIn("targets", payload)
        self.assertIn("summary", payload)
        names = {t["target_name"] for t in payload["targets"]}
        self.assertEqual(names, {"soul", "user", "memory", "skills"})
        required = {
            "target_name", "last_compiled_at", "last_runtime_observed_at",
            "compile_status", "drift_status", "managed_item_count",
            "unmanaged_item_count", "divergent_item_count",
            "last_compiled_fingerprint", "current_runtime_fingerprint",
        }
        for t in payload["targets"]:
            self.assertTrue(required.issubset(t.keys()), required - t.keys())
        # target detail adds diff + events
        detail = runtime.target_detail(led, "memory")
        self.assertIn("diff", detail)
        self.assertIn("events", detail)
        self.assertTrue(detail["events"]["compiles"])

    # 6. a failed write → compile_failed ---------------------------------------
    def test_compile_failed_is_reported(self):
        self.write_memory("memory", "Will fail to write.")
        led = self.ledger()
        snapshot.bootstrap(led)
        orig = compiler._write
        try:
            def boom(path, content):
                raise OSError("disk full")
            compiler._write = boom
            res = runtime.compile_all(led)
        finally:
            compiler._write = orig
        self.assertFalse(res["ok"])
        self.assertTrue(any(r["status"] == "compile_failed" for r in res["results"]))
        st = runtime._target_status(led, "memory")
        self.assertEqual(st["compile_status"], "compile_failed")

    # A Loom edit (direct file write) keeps the target managed, not drifted ------
    def test_loom_edit_stays_in_sync_and_managed(self):
        led = self._seed_and_compile()
        # edit a memory entry through Loom (writes USER.md directly + records an
        # override snapshot). This must NOT read as external drift.
        service.record_edit(led, "user", entry_key("User likes tea."),
                            "User likes oolong tea.")
        st = runtime._target_status(led, "user")
        self.assertEqual(st["drift_status"], "in_sync")
        self.assertEqual(st["compile_status"], "compiled")
        self.assertEqual(st["divergent_item_count"], 0)
        self.assertEqual(st["unmanaged_item_count"], 0)
        self.assertGreaterEqual(st["managed_item_count"], 1)

    # SOUL target: compiled from its DB version, then drift detected -----------
    def test_soul_target_compile_and_drift(self):
        self.write_memory("memory", "x")           # so bootstrap has something
        led = self.ledger()
        soul.save(led, "I am a careful assistant.")
        runtime.compile_all(led)
        st = runtime._target_status(led, "soul")
        self.assertEqual(st["compile_status"], "compiled")
        self.assertEqual(st["drift_status"], "in_sync")
        # external edit to SOUL.md
        from hermes_loom import config
        config.soul_md_path().write_text("Tampered identity.", encoding="utf-8")
        st2 = runtime._target_status(led, "soul")
        self.assertEqual(st2["drift_status"], "drifted")
        self.assertEqual(st2["divergent_item_count"], 1)
