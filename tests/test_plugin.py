"""Part 10.8 + real-contract — the plugin registers against the actual Hermes
PluginContext API (register_hook(name, cb), register_tool(name=,toolset=,schema=,
handler=,...)) and the post_tool_call keyword-callback shape, and never crashes
the host even when ctx is partial/empty or callbacks throw."""

import json
from base import LoomTestCase
from hermes_loom import plugin


class FakeCtx:
    """Mimics the real Hermes 0.16 PluginContext surface."""
    def __init__(self, fail_hooks=False):
        self.hooks = {}
        self.tools = {}
        self.fail_hooks = fail_hooks

    def register_hook(self, hook_name, callback):
        if self.fail_hooks:
            raise RuntimeError("hook point unavailable")
        self.hooks.setdefault(hook_name, []).append(callback)

    def register_tool(self, name, toolset, schema, handler, description="", **kw):
        self.tools[name] = {"toolset": toolset, "schema": schema, "handler": handler}


class MinimalCtx:
    """A context exposing nothing — worst-case Hermes build."""


class TestPlugin(LoomTestCase):
    def test_register_binds_real_hooks_and_tool(self):
        self.write_memory("user", "fact")
        ctx = FakeCtx()
        info = plugin.register(ctx)
        self.assertEqual(info["name"], "hermes-loom")
        self.assertIn("post_tool_call", ctx.hooks)
        self.assertIn("on_session_start", ctx.hooks)
        self.assertIn("loom_sync", ctx.tools)
        self.assertEqual(ctx.tools["loom_sync"]["toolset"], "loom")

    def test_post_tool_call_records_memory(self):
        self.write_memory("user", "fact")
        ctx = FakeCtx()
        plugin.register(ctx)
        cb = ctx.hooks["post_tool_call"][0]
        # fire it exactly like Hermes' tool executor does (keyword-only)
        cb(tool_name="memory",
           args={"action": "add", "target": "user", "content": "User likes tea."},
           result={"success": True, "message": "Entry added."},
           session_id="sess-9", tool_call_id="call_42")
        led = self.ledger()
        evs = led.query_events(kind="memory_added")
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["after_text"], "User likes tea.")
        self.assertEqual(evs[0]["source_session_id"], "sess-9")
        self.assertEqual(evs[0]["source_hint"], "plugin_hook")

    def test_post_tool_call_records_skill(self):
        self.write_memory("user", "fact")
        ctx = FakeCtx()
        plugin.register(ctx)
        cb = ctx.hooks["post_tool_call"][0]
        cb(tool_name="skill_manage",
           args={"action": "edit", "skill_name": "demo", "skill_md": "new body"},
           result={"success": True}, session_id="sess-1", tool_call_id="c2")
        led = self.ledger()
        self.assertEqual(len(led.query_events(kind="skill_edited")), 1)

    def test_post_tool_call_ignores_failed_and_readonly(self):
        self.write_memory("user", "fact")
        ctx = FakeCtx()
        plugin.register(ctx)
        cb = ctx.hooks["post_tool_call"][0]
        cb(tool_name="memory", args={"action": "add", "content": "x"},
           result={"success": False})           # failed -> ignored
        cb(tool_name="skill_view", args={"name": "demo"}, result={"success": True})  # read-only
        led = self.ledger()
        # assert by kind (the background on_session_start bootstrap may add a
        # memory_snapshot_imported for USER.md, which is unrelated to these calls)
        self.assertEqual(len(led.query_events(kind="memory_added")), 0)
        self.assertEqual(len(led.query_events(kind="memory_replaced")), 0)
        self.assertEqual([e for e in led.query_events(target_type="skill")
                          if e["kind"] != "skill_snapshot_imported"], [])

    def test_args_may_be_json_string(self):
        self.write_memory("user", "fact")
        ctx = FakeCtx()
        plugin.register(ctx)
        cb = ctx.hooks["post_tool_call"][0]
        cb(tool_name="memory",
           args=json.dumps({"action": "add", "target": "user", "content": "from string"}),
           result=json.dumps({"success": True}), session_id="s", tool_call_id="c")
        led = self.ledger()
        self.assertEqual(led.query_events(kind="memory_added")[0]["after_text"], "from string")

    def test_register_survives_ctx_without_anything(self):
        info = plugin.register(MinimalCtx())
        self.assertEqual(info["hooks"], [])

    def test_register_survives_failing_hooks(self):
        info = plugin.register(FakeCtx(fail_hooks=True))
        self.assertEqual(info["hooks"], [])

    def test_callback_swallows_exceptions(self):
        bad = plugin._safe(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        self.assertIsNone(bad())

    def test_root_init_reexports_register(self):
        """The installable plugin root must expose register(ctx)."""
        import importlib
        root = importlib.import_module("__init__") if False else None  # avoid name clash
        # import the repo-root __init__ as a module file
        import os
        import importlib.util
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "__init__.py")
        spec = importlib.util.spec_from_file_location("hermes_loom_plugin_root", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertTrue(callable(mod.register))
