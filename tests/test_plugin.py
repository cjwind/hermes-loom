"""Part 10.8 — the Hermes plugin registers against whatever ctx offers and never
crashes the host, even when hooks are missing or callbacks throw."""

from base import LoomTestCase
from hermes_loom import plugin


class FakeCtx:
    """Mimics a Hermes plugin context exposing register_hook / register_tool."""
    def __init__(self, fail_hooks=False):
        self.hooks = {}
        self.tools = {}
        self.fail_hooks = fail_hooks

    def register_hook(self, name, cb):
        if self.fail_hooks:
            raise RuntimeError("this hook point not supported")
        self.hooks[name] = cb

    def register_tool(self, name, fn, description=None):
        self.tools[name] = fn


class MinimalCtx:
    """A context that exposes NOTHING — worst case Hermes version."""
    pass


class TestPlugin(LoomTestCase):
    def test_register_binds_hooks(self):
        self.write_memory("user", "fact")
        ctx = FakeCtx()
        info = plugin.register(ctx)
        self.assertEqual(info["name"], "hermes-loom")
        self.assertTrue(ctx.hooks)  # at least one hook bound
        self.assertIn("loom_sync", ctx.tools)

    def test_memory_hook_records_event(self):
        self.write_memory("user", "fact")
        ctx = FakeCtx()
        plugin.register(ctx)
        # find the memory hook and fire it like Hermes would
        hook = ctx.hooks.get("memory_write") or ctx.hooks.get("on_memory_write")
        self.assertIsNotNone(hook)
        hook("add", "user", "User likes tea.", session_id=None)
        led = self.ledger()
        self.assertEqual(len(led.query_events(kind="memory_added")), 1)

    def test_register_survives_ctx_without_hooks(self):
        """No register_hook/tool at all -> must not raise; falls back silently."""
        info = plugin.register(MinimalCtx())
        self.assertEqual(info["hooks"], [])

    def test_register_survives_failing_hooks(self):
        info = plugin.register(FakeCtx(fail_hooks=True))
        self.assertEqual(info["hooks"], [])  # none bound, but no crash

    def test_callback_swallows_exceptions(self):
        bad = plugin._safe(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        self.assertIsNone(bad())  # swallowed, returns None
