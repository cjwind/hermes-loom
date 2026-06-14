"""Local HTTP API for Hermes Loom — stdlib only (no FastAPI dependency).

Serves the JSON endpoints the UI needs plus the static UI itself. Local-first:
binds to 127.0.0.1, no auth, single user. Each request opens its own ledger
connection (SQLite connections are not shared across threads).

Endpoints (see README for full list):
  GET  /api/events
  GET  /api/events/{id}
  GET  /api/memory/current
  GET  /api/skills
  GET  /api/skills/{name}
  GET  /api/sessions/{id}/context
  POST /api/overrides/memory/edit
  POST /api/overrides/memory/delete
  POST /api/overrides/skill/edit
  POST /api/overrides/skill/delete
  POST /api/maintenance/reconcile     (run snapshot-diff fallback now)
  POST /api/maintenance/ingest        (backfill from state.db)
"""

from __future__ import annotations

import json
import logging
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import config, ingest, service, snapshot
from .ledger import Ledger
from .overrides import OverrideError

log = logging.getLogger("hermes_loom.api")


class _Router:
    def __init__(self):
        self.routes = []  # (method, regex, handler)

    def add(self, method, pattern, handler):
        self.routes.append((method, re.compile(f"^{pattern}$"), handler))

    def match(self, method, path):
        for m, rx, h in self.routes:
            if m != method:
                continue
            mo = rx.match(path)
            if mo:
                return h, mo.groupdict()
        return None, None


router = _Router()


def route(method, pattern):
    def deco(fn):
        router.add(method, pattern, fn)
        return fn
    return deco


# ---- handlers (each receives (ledger, params, query, body) -> (status, obj)) ----

@route("GET", r"/api/events")
def h_events(ledger, params, query, body):
    f = {}
    if "target_type" in query: f["target_type"] = query["target_type"][0]
    if "kind" in query: f["kind"] = query["kind"][0]
    if "status" in query: f["status"] = query["status"][0]
    if "session_id" in query: f["session_id"] = query["session_id"][0]
    if "recent_days" in query: f["recent_days"] = float(query["recent_days"][0])
    if "limit" in query: f["limit"] = int(query["limit"][0])
    return 200, service.list_events(ledger, **f)


@route("GET", r"/api/events/(?P<id>\d+)")
def h_event_detail(ledger, params, query, body):
    detail = service.event_detail(ledger, int(params["id"]))
    if not detail:
        return 404, {"error": "event not found"}
    return 200, detail


@route("GET", r"/api/memory/current")
def h_memory(ledger, params, query, body):
    return 200, service.current_memory(ledger)


# ---- Inspector records --------------------------------------------------

@route("GET", r"/api/status")
def h_status(ledger, params, query, body):
    return 200, service.auto_deposit_status(ledger)


@route("GET", r"/api/records")
def h_records(ledger, params, query, body):
    return 200, service.build_records(ledger)


@route("GET", r"/api/records/(?P<rid>.+)")
def h_record_detail(ledger, params, query, body):
    from urllib.parse import unquote
    detail = service.record_detail(ledger, unquote(params["rid"]))
    if not detail:
        return 404, {"error": "record not found"}
    return 200, detail


def _record_target(body):
    tt = body.get("target_type")
    tk = body.get("target_key")
    if not tt or not tk:
        # accept an id "type:key" as a convenience
        rid = body.get("id", "")
        tt, _, tk = rid.partition(":")
    if not tt or not tk:
        raise KeyError("target_type/target_key (or id) required")
    return tt, tk


@route("POST", r"/api/records/edit")
def h_record_edit(ledger, params, query, body):
    try:
        tt, tk = _record_target(body)
        res = service.record_edit(ledger, tt, tk, body["new_value"], reason=body.get("reason"))
        return 200, {"ok": True, **res}
    except (KeyError, OverrideError) as e:
        return 400, {"ok": False, "error": str(e)}


@route("POST", r"/api/records/delete")
def h_record_delete(ledger, params, query, body):
    try:
        tt, tk = _record_target(body)
        res = service.record_delete(ledger, tt, tk, reason=body.get("reason"))
        return 200, {"ok": True, **res}
    except (KeyError, OverrideError) as e:
        return 400, {"ok": False, "error": str(e)}


@route("POST", r"/api/records/add")
def h_record_add(ledger, params, query, body):
    """Append a memory/user entry (used to undo a delete)."""
    try:
        from . import overrides as _ov
        store = body.get("store_type") or body.get("target_type") or "memory"
        store = "user" if store == "user" else "memory"
        res = _ov.add_memory_entry(ledger, store, body["text"], reason=body.get("reason"))
        return 200, {"ok": True, **res}
    except (KeyError, OverrideError) as e:
        return 400, {"ok": False, "error": str(e)}


@route("POST", r"/api/records/annotate")
def h_record_annotate(ledger, params, query, body):
    try:
        tt, tk = _record_target(body)
        from . import overrides as _ov
        res = _ov.annotate_record(ledger, tt, tk, body.get("text", ""))
        return 200, {"ok": True, **res}
    except KeyError as e:
        return 400, {"ok": False, "error": str(e)}


@route("POST", r"/api/records/reclassify")
def h_record_reclassify(ledger, params, query, body):
    try:
        tt, tk = _record_target(body)
        from . import overrides as _ov
        res = _ov.reclassify_record(ledger, tt, tk, body["to_cat"], from_cat=body.get("from_cat"))
        return 200, {"ok": True, **res}
    except KeyError as e:
        return 400, {"ok": False, "error": str(e)}


@route("POST", r"/api/records/pin")
def h_record_pin(ledger, params, query, body):
    try:
        tt, tk = _record_target(body)
        from . import overrides as _ov
        res = _ov.set_pin(ledger, tt, tk, bool(body.get("pinned", True)))
        return 200, {"ok": True, **res}
    except KeyError as e:
        return 400, {"ok": False, "error": str(e)}


@route("GET", r"/api/skills")
def h_skills(ledger, params, query, body):
    return 200, service.list_skills(ledger)


@route("GET", r"/api/skills/(?P<name>[^/]+)")
def h_skill_detail(ledger, params, query, body):
    from urllib.parse import unquote
    detail = service.skill_detail(ledger, unquote(params["name"]))
    if not detail:
        return 404, {"error": "skill not found"}
    return 200, detail


@route("GET", r"/api/sessions/(?P<id>[^/]+)/context")
def h_session_ctx(ledger, params, query, body):
    from urllib.parse import unquote
    limit = int(query.get("limit", ["20"])[0])
    return 200, service.session_context(ledger, unquote(params["id"]), limit=limit)


@route("POST", r"/api/overrides/memory/edit")
def h_mem_edit(ledger, params, query, body):
    try:
        res = service.apply_memory_edit(
            ledger, body["store_type"], body["entry_key"], body["new_text"],
            reason=body.get("reason"),
        )
        return 200, {"ok": True, **res}
    except (KeyError, OverrideError) as e:
        return 400, {"ok": False, "error": str(e)}


@route("POST", r"/api/overrides/memory/delete")
def h_mem_delete(ledger, params, query, body):
    try:
        res = service.apply_memory_delete(
            ledger, body["store_type"], body["entry_key"], reason=body.get("reason"),
        )
        return 200, {"ok": True, **res}
    except (KeyError, OverrideError) as e:
        return 400, {"ok": False, "error": str(e)}


@route("POST", r"/api/overrides/skill/edit")
def h_skill_edit(ledger, params, query, body):
    try:
        res = service.apply_skill_edit(
            ledger, body["name"], body["new_content"], reason=body.get("reason"),
        )
        return 200, {"ok": True, **res}
    except (KeyError, OverrideError) as e:
        return 400, {"ok": False, "error": str(e)}


@route("POST", r"/api/overrides/skill/delete")
def h_skill_delete(ledger, params, query, body):
    try:
        res = service.apply_skill_delete(
            ledger, body["name"], hard=bool(body.get("hard", False)), reason=body.get("reason"),
        )
        return 200, {"ok": True, **res}
    except (KeyError, OverrideError) as e:
        return 400, {"ok": False, "error": str(e)}


@route("POST", r"/api/maintenance/reconcile")
def h_reconcile(ledger, params, query, body):
    return 200, {"ok": True, "result": snapshot.reconcile_all(ledger)}


@route("POST", r"/api/maintenance/ingest")
def h_ingest(ledger, params, query, body):
    return 200, {"ok": True, "result": ingest.ingest_state_db(ledger)}


@route("GET", r"/api/health")
def h_health(ledger, params, query, body):
    return 200, {"ok": True, "db": str(ledger.db_path), "hermes_home": str(config.hermes_home())}


# ---- HTTP plumbing ----------------------------------------------------------

class LoomHandler(BaseHTTPRequestHandler):
    server_version = "HermesLoom/0.1"

    def log_message(self, fmt, *args):  # quieter logs
        log.debug("%s - %s", self.address_string(), fmt % args)

    def _send(self, status, obj):
        payload = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def _serve_static(self, path):
        ui = config.ui_dir()
        rel = path.lstrip("/")
        if rel in ("", "index.html"):
            rel = "index.html"
        target = (ui / rel).resolve()
        if not str(target).startswith(str(ui.resolve())) or not target.is_file():
            self.send_error(404, "not found")
            return
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
        }.get(target.suffix, "application/octet-stream")
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _dispatch(self, method):
        parsed = urlparse(self.path)
        path = parsed.path
        if not path.startswith("/api/"):
            if method == "GET":
                return self._serve_static(path)
            return self.send_error(404)
        handler, params = router.match(method, path)
        if not handler:
            return self._send(404, {"error": f"no route for {method} {path}"})
        body = {}
        if method == "POST":
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b""
            if raw:
                try:
                    body = json.loads(raw)
                except json.JSONDecodeError:
                    return self._send(400, {"error": "invalid JSON body"})
        ledger = Ledger()
        try:
            status, obj = handler(ledger, params, parse_qs(parsed.query), body)
            self._send(status, obj)
        except Exception as e:  # noqa: BLE001
            log.exception("handler error")
            self._send(500, {"error": str(e)})
        finally:
            ledger.close()

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def make_server(host="127.0.0.1", port=8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), LoomHandler)


def serve(host="127.0.0.1", port=8765):
    # ensure DB + bootstrap exist before serving
    ledger = Ledger()
    try:
        snapshot.bootstrap(ledger)
    finally:
        ledger.close()
    httpd = make_server(host, port)
    log.info("Hermes Loom API on http://%s:%s", host, port)
    print(f"Hermes Loom running on http://{host}:{port}  (UI at /)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()
