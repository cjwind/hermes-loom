"""Tags + pre_llm_call recall: tag storage, tagger (LLM + keyword), recall,
and the plugin hook that injects tag-matched records as context."""

import json
import os
from unittest import mock
from base import LoomTestCase
from hermes_loom import service, tagger, plugin


class TestTagStorage(LoomTestCase):
    def test_set_get_tags_keyed_by_content(self):
        led = self.ledger()
        led.set_tags("ekey", ["A", "b", "B", " a ", ""])   # dedupe (case-insens), strip, drop empty
        self.assertEqual(led.get_tags("ekey"), ["A", "b"])
        self.assertEqual(led.all_tags(), ["A", "b"])

    def test_build_records_attaches_tags(self):
        self.write_memory("user", "User is allergic to shellfish")
        led = self.ledger()
        r = service.build_records(led)["records"][0]
        service.record_set_tags(led, r["target_key"], ["food", "health"])
        r2 = next(x for x in service.build_records(led)["records"] if x["target_key"] == r["target_key"])
        self.assertEqual(sorted(r2["tags"]), ["food", "health"])


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

        # message never literally contains "food", but the (mocked) LLM maps it
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

    def test_llm_param_shape_fallback(self):
        # gpt-5-style: first variant (max_completion_tokens) "works"; ensure a
        # 400 on the first variant retries the second instead of failing.
        os.environ["LOOM_LLM_BASE_URL"] = "http://fake"
        os.environ["LOOM_LLM_MODEL"] = "gpt-5"
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in ("LOOM_LLM_BASE_URL", "LOOM_LLM_MODEL")])
        import urllib.error

        class FakeResp:
            def read(self): return json.dumps({"choices": [{"message": {"content": '["food"]'}}]}).encode()
            def __enter__(self): return self
            def __exit__(self, *a): return False
        calls = {"n": 0}
        def fake_urlopen(req, timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise urllib.error.HTTPError("u", 400, "Bad Request", {}, None)
            return FakeResp()
        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            matched, method = tagger.resolve_tags("cook for the allergy?", ["food"])
        self.assertEqual(method, "llm")
        self.assertEqual(matched, ["food"])
        self.assertEqual(calls["n"], 2)  # fell back to the 2nd variant

    def test_llm_failure_falls_back_to_keyword(self):
        os.environ["LOOM_LLM_BASE_URL"] = "http://fake"
        os.environ["LOOM_LLM_MODEL"] = "m"
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in ("LOOM_LLM_BASE_URL", "LOOM_LLM_MODEL")])
        with mock.patch("urllib.request.urlopen", side_effect=OSError("boom")):
            matched, method = tagger.resolve_tags("food please", ["food"])
        self.assertEqual(method, "keyword")
        self.assertEqual(matched, ["food"])


class TestRecall(LoomTestCase):
    def _seed(self):
        self.write_memory("user", "allergic to shellfish\n§\nwindow seats on flights")
        led = self.ledger()
        recs = service.build_records(led)["records"]
        food = next(r for r in recs if "shellfish" in r["versions"][r["active"]]["value"])
        travel = next(r for r in recs if "window seats" in r["versions"][r["active"]]["value"])
        service.record_set_tags(led, food["target_key"], ["food"])
        service.record_set_tags(led, travel["target_key"], ["travel"])
        return led

    def test_recall_injects_only_matching_tag(self):
        led = self._seed()
        res = service.recall(led, "any food restrictions?")
        self.assertEqual(res["tags"], ["food"])
        self.assertEqual(res["count"], 1)
        self.assertIn("shellfish", res["context"])
        self.assertNotIn("window seats", res["context"])

    def test_recall_empty_when_no_match(self):
        led = self._seed()
        res = service.recall(led, "tell me a joke")
        self.assertEqual(res["count"], 0)
        self.assertEqual(res["context"], "")

    def test_recall_empty_when_no_tags(self):
        self.write_memory("user", "untagged fact")
        led = self.ledger()
        res = service.recall(led, "anything")
        self.assertEqual(res["method"], "none")
        self.assertEqual(res["context"], "")


class TestRecallLog(LoomTestCase):
    def _tagged(self):
        self.write_memory("user", "allergic to shellfish")
        led = self.ledger()
        r = service.build_records(led)["records"][0]
        service.record_set_tags(led, r["target_key"], ["food"])
        return led

    def test_recall_logs_when_log_true(self):
        led = self._tagged()
        service.recall(led, "food allergies?", log=True, session_id="s1")
        log = service.recall_log(led)["recalls"]
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["method"], "keyword")
        self.assertEqual(log[0]["tags"], ["food"])
        self.assertEqual(log[0]["count"], 1)
        self.assertEqual(log[0]["session_id"], "s1")
        self.assertEqual(log[0]["records"][0]["value"], "allergic to shellfish")

    def test_recall_does_not_log_by_default(self):
        led = self._tagged()
        service.recall(led, "food allergies?")            # log defaults False
        self.assertEqual(service.recall_log(led)["recalls"], [])

    def test_no_log_when_no_injection(self):
        led = self._tagged()
        service.recall(led, "tell me a joke", log=True)   # no tag match → no log
        self.assertEqual(service.recall_log(led)["recalls"], [])

    def test_plugin_hook_logs_injection(self):
        led = self._tagged()
        plugin.LoomPlugin().on_pre_llm_call(user_message="what food to avoid?", session_id="sx")
        self.assertEqual(len(service.recall_log(led)["recalls"]), 1)


class TestPluginPreLlmCall(LoomTestCase):
    def test_hook_injects_tagged_context(self):
        self.write_memory("user", "allergic to shellfish")
        led = self.ledger()
        r = service.build_records(led)["records"][0]
        service.record_set_tags(led, r["target_key"], ["food"])
        out = plugin.LoomPlugin().on_pre_llm_call(user_message="what food should I avoid?")
        self.assertIsNotNone(out)
        self.assertIn("shellfish", out["context"])

    def test_hook_no_message_returns_none(self):
        self.write_memory("user", "x")
        self.assertIsNone(plugin.LoomPlugin().on_pre_llm_call(user_message=""))

    def test_hook_registered(self):
        self.write_memory("user", "x")
        class Ctx:
            def __init__(s): s.hooks = {}
            def register_hook(s, n, c): s.hooks.setdefault(n, []).append(c)
            def register_tool(s, **k): pass
        ctx = Ctx()
        info = plugin.register(ctx)
        self.assertIn("pre_llm_call", ctx.hooks)
        self.assertIn("pre_llm_call", info["hooks"])
