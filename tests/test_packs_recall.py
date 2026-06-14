"""Packs (middle memory layer) + pre_llm_call recall: pack CRUD, tagger
(LLM + keyword), pack selection from a user message, and the plugin hook that
injects matching packs as context."""

import json
import os
from unittest import mock
from base import LoomTestCase
from hermes_loom import service, tagger, plugin


class TestPackStorage(LoomTestCase):
    def test_crud_roundtrip(self):
        led = self.ledger()
        pid = led.create_pack("風浪板", ["運動", "戶外"], "我玩風浪板三年了。")
        p = led.get_pack(pid)
        self.assertEqual(p["title"], "風浪板")
        self.assertEqual(p["tags"], ["運動", "戶外"])
        self.assertTrue(p["enabled"])
        led.update_pack(pid, title="風浪板 windsurf", tags=["sport"], content="updated", enabled=False)
        p = led.get_pack(pid)
        self.assertEqual(p["title"], "風浪板 windsurf")
        self.assertEqual(p["tags"], ["sport"])
        self.assertFalse(p["enabled"])
        self.assertEqual(len(led.list_packs()), 1)
        self.assertEqual(led.list_packs(enabled_only=True), [])
        self.assertTrue(led.delete_pack(pid))
        self.assertIsNone(led.get_pack(pid))

    def test_tags_cleaned(self):
        led = self.ledger()
        pid = led.create_pack("t", ["A", "a", " B ", ""], "c")
        self.assertEqual(led.get_pack(pid)["tags"], ["A", "B"])

    def test_save_pack_validates(self):
        led = self.ledger()
        with self.assertRaises(ValueError):
            service.save_pack(led, title="", tags=[], content="x")
        with self.assertRaises(ValueError):
            service.save_pack(led, title="x", tags=[], content="  ")
        with self.assertRaises(ValueError):
            service.save_pack(led, pack_id=999, title="x", tags=[], content="y")


class TestTaggerKeyword(LoomTestCase):
    def test_keyword_fallback_when_no_llm(self):
        os.environ.pop("LOOM_LLM_BASE_URL", None)
        os.environ.pop("LOOM_LLM_MODEL", None)
        matched, method = tagger.resolve_tags("any food notes for dinner?", ["food", "travel"])
        self.assertEqual(method, "keyword")
        self.assertEqual(matched, ["food"])

    def test_empty_inputs(self):
        self.assertEqual(tagger.resolve_tags("", ["x"]), ([], "none"))
        self.assertEqual(tagger.resolve_tags("hi", []), ([], "none"))

    def test_parse_tag_array_tolerant(self):
        self.assertEqual(tagger._parse_tag_array('["a","b"]'), ["a", "b"])
        self.assertEqual(tagger._parse_tag_array('```json\n["a"]\n```'), ["a"])
        self.assertEqual(tagger._parse_tag_array('here: ["a", "b"] ok'), ["a", "b"])
        self.assertEqual(tagger._parse_tag_array("nope"), [])


class TestTaggerLLM(LoomTestCase):
    def test_llm_semantic_resolution(self):
        os.environ["LOOM_LLM_BASE_URL"] = "http://fake"
        os.environ["LOOM_LLM_MODEL"] = "m"
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in ("LOOM_LLM_BASE_URL", "LOOM_LLM_MODEL")])

        class FakeResp:
            def __init__(self, body): self._b = body
            def read(self): return json.dumps(self._b).encode()
            def __enter__(self): return self
            def __exit__(self, *a): return False
        body = {"choices": [{"message": {"content": '["food"]'}}]}
        with mock.patch("urllib.request.urlopen", return_value=FakeResp(body)):
            matched, method = tagger.resolve_tags("what can I cook for the allergy?", ["food", "travel"])
        self.assertEqual(method, "llm")
        self.assertEqual(matched, ["food"])

    def test_llm_failure_falls_back_to_keyword(self):
        os.environ["LOOM_LLM_BASE_URL"] = "http://fake"
        os.environ["LOOM_LLM_MODEL"] = "m"
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in ("LOOM_LLM_BASE_URL", "LOOM_LLM_MODEL")])
        with mock.patch("urllib.request.urlopen", side_effect=OSError("boom")):
            matched, method = tagger.resolve_tags("food please", ["food"])
        self.assertEqual(method, "keyword")
        self.assertEqual(matched, ["food"])


class TestPackRecall(LoomTestCase):
    def _seed(self):
        led = self.ledger()
        led.create_pack("飲食", ["food"], "對甲殼類過敏。")
        led.create_pack("旅行", ["travel"], "搭飛機喜歡靠窗。")
        return led

    def test_recall_injects_only_matching_pack(self):
        led = self._seed()
        res = service.recall(led, "any food restrictions?")
        self.assertEqual(res["tags"], ["food"])
        self.assertEqual(res["count"], 1)
        self.assertIn("甲殼類", res["context"])
        self.assertNotIn("靠窗", res["context"])
        self.assertEqual(res["records"][0]["id"], "pack:1")
        self.assertEqual(res["records"][0]["title"], "飲食")

    def test_recall_matches_by_title_too(self):
        led = self.ledger()
        led.create_pack("windsurf", [], "三年經驗")
        res = service.recall(led, "tell me about windsurf gear")
        self.assertEqual(res["count"], 1)
        self.assertIn("三年經驗", res["context"])

    def test_disabled_pack_never_injected(self):
        led = self.ledger()
        pid = led.create_pack("飲食", ["food"], "對甲殼類過敏。")
        led.update_pack(pid, title="飲食", tags=["food"], content="對甲殼類過敏。", enabled=False)
        res = service.recall(led, "any food notes?")
        self.assertEqual(res["method"], "none")
        self.assertEqual(res["count"], 0)

    def test_recall_empty_when_no_match(self):
        led = self._seed()
        res = service.recall(led, "tell me a joke")
        self.assertEqual(res["count"], 0)
        self.assertEqual(res["context"], "")

    def test_recall_empty_when_no_packs(self):
        led = self.ledger()
        res = service.recall(led, "anything")
        self.assertEqual(res["method"], "none")
        self.assertEqual(res["context"], "")


class TestRecallLog(LoomTestCase):
    def _seed(self):
        led = self.ledger()
        led.create_pack("飲食", ["food"], "對甲殼類過敏。")
        return led

    def test_recall_logs_when_log_true(self):
        led = self._seed()
        service.recall(led, "food allergies?", log=True, session_id="s1")
        log = service.recall_log(led)["recalls"]
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["method"], "keyword")
        self.assertEqual(log[0]["tags"], ["food"])
        self.assertEqual(log[0]["count"], 1)
        self.assertEqual(log[0]["session_id"], "s1")
        self.assertEqual(log[0]["records"][0]["title"], "飲食")

    def test_recall_does_not_log_by_default(self):
        led = self._seed()
        service.recall(led, "food allergies?")
        self.assertEqual(service.recall_log(led)["recalls"], [])

    def test_no_log_when_no_injection(self):
        led = self._seed()
        service.recall(led, "tell me a joke", log=True)
        self.assertEqual(service.recall_log(led)["recalls"], [])

    def test_plugin_hook_logs_injection(self):
        self._seed()
        plugin.LoomPlugin().on_pre_llm_call(user_message="what food to avoid?", session_id="sx")
        self.assertEqual(len(service.recall_log(self.ledger())["recalls"]), 1)


class TestPluginPreLlmCall(LoomTestCase):
    def test_hook_injects_pack_context(self):
        led = self.ledger()
        led.create_pack("飲食", ["food"], "對甲殼類過敏。")
        out = plugin.LoomPlugin().on_pre_llm_call(user_message="what food should I avoid?")
        self.assertIsNotNone(out)
        self.assertIn("甲殼類", out["context"])

    def test_hook_no_message_returns_none(self):
        self.ledger().create_pack("飲食", ["food"], "x")
        self.assertIsNone(plugin.LoomPlugin().on_pre_llm_call(user_message=""))
