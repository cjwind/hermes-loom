"""Real auto-deposit status: plugin enabled (config.yaml) + gateway + recent hook."""

import json
from base import LoomTestCase
from hermes_loom import hermes_state, service
from hermes_loom.observer import Observer


CONFIG_ENABLED = """\
some_key: 1
plugins:
  enabled:
  - hermes-loom
  - orkaos
  disabled:
  - basic
other: 2
"""

CONFIG_DISABLED = """\
plugins:
  enabled:
  - orkaos
  disabled:
  - hermes-loom
"""


class TestStatus(LoomTestCase):
    def _write_config(self, text):
        (self.hermes_home / "config.yaml").write_text(text, encoding="utf-8")

    def _write_plugin(self):
        d = self.hermes_home / "plugins" / "hermes-loom"
        d.mkdir(parents=True, exist_ok=True)
        (d / "plugin.yaml").write_text("name: hermes-loom\n", encoding="utf-8")

    def _write_gateway(self, running):
        (self.hermes_home / "gateway_state.json").write_text(
            json.dumps({"gateway_state": "running" if running else "stopped"}), encoding="utf-8")

    def test_offline_when_not_installed(self):
        led = self.ledger()
        s = service.auto_deposit_status(led)
        self.assertEqual(s["state"], "offline")
        self.assertFalse(s["plugin"]["installed"])

    def test_enabled_but_no_gateway(self):
        self._write_config(CONFIG_ENABLED)
        self._write_plugin()
        led = self.ledger()
        s = service.auto_deposit_status(led)
        self.assertTrue(s["plugin"]["enabled"])
        self.assertEqual(s["state"], "enabled")

    def test_live_when_enabled_and_gateway_running(self):
        self._write_config(CONFIG_ENABLED)
        self._write_plugin()
        self._write_gateway(True)
        led = self.ledger()
        s = service.auto_deposit_status(led)
        self.assertEqual(s["state"], "live")
        self.assertEqual(s["label"], "自動沉澱進行中")

    def test_disabled_in_config_is_offline(self):
        self._write_config(CONFIG_DISABLED)
        self._write_plugin()
        self._write_gateway(True)
        led = self.ledger()
        s = service.auto_deposit_status(led)
        self.assertFalse(s["plugin"]["enabled"])
        self.assertEqual(s["state"], "offline")

    def test_last_plugin_hook_reported(self):
        self._write_config(CONFIG_ENABLED)
        self._write_plugin()
        self._write_gateway(True)
        led = self.ledger()
        Observer(led).on_memory_write("add", "user", "x", source_hint="plugin_hook", capture_window=False)
        s = service.auto_deposit_status(led)
        self.assertIsNotNone(s["last_plugin_hook"])

    def test_config_parser_lists(self):
        self._write_config(CONFIG_ENABLED)
        lists = hermes_state._plugins_lists()
        self.assertIn("hermes-loom", lists["enabled"])
        self.assertIn("basic", lists["disabled"])
