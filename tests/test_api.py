"""Part 10.5 — the Local API returns correct event detail and supports overrides
end-to-end over real HTTP."""

import json
import threading
import urllib.request
from base import LoomTestCase
from hermes_loom import api
from hermes_loom.observer import Observer


class TestApi(LoomTestCase):
    def setUp(self):
        super().setUp()
        # seed one memory file + one event
        self.write_memory("user", "User likes tea.")
        led = self.ledger()
        Observer(led).on_memory_write("add", "user", "User likes tea.", capture_window=False)
        self.httpd = api.make_server(port=0)  # ephemeral port
        self.port = self.httpd.server_address[1]
        self.t = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.t.start()
        self.addCleanup(self.httpd.shutdown)

    def _get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
            return json.loads(r.read())

    def _post(self, path, body):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())

    def test_events_and_detail(self):
        evs = self._get("/api/events")
        self.assertEqual(evs["count"], 1)
        eid = evs["events"][0]["id"]
        detail = self._get(f"/api/events/{eid}")
        self.assertEqual(detail["after"], "User likes tea.")
        self.assertIn("event", detail)
        self.assertIn("related_overrides", detail)

    def test_memory_current(self):
        d = self._get("/api/memory/current")
        self.assertTrue(d["user"]["exists"])
        self.assertEqual(d["user"]["entries"][0]["text"], "User likes tea.")

    def test_override_via_api_changes_file(self):
        d = self._get("/api/memory/current")
        key = d["user"]["entries"][0]["key"]
        res = self._post("/api/overrides/memory/edit",
                         {"store_type": "user", "entry_key": key, "new_text": "User loves tea."})
        self.assertTrue(res["ok"])
        on_disk = (self.hermes_home / "memories" / "USER.md").read_text()
        self.assertIn("User loves tea.", on_disk)

    def test_bad_override_returns_400(self):
        try:
            self._post("/api/overrides/memory/edit",
                       {"store_type": "user", "entry_key": "nope", "new_text": "x"})
            self.fail("expected HTTP 400")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)
