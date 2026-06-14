"""Hermes plugin — live observation entrypoint.

Written against the **real** Hermes 0.16 plugin contract (verified against the
installed runtime), not a guess:

  * Hermes discovers a plugin from ``$HERMES_HOME/plugins/<name>/`` via a
    ``plugin.yaml`` manifest + an ``__init__.py`` exposing ``register(ctx)``.
  * ``ctx.register_hook(hook_name, callback)`` — valid hooks include
    ``post_tool_call`` and ``on_session_start``. Unknown names only warn.
  * Memory and skill changes are **not** dedicated hooks — they flow through the
    ``memory`` and ``skill_manage`` *tools*. We therefore observe them via
    ``post_tool_call``, whose callback is invoked with keyword args:
      ``(*, tool_name="", args=None, result=None, session_id="",
          tool_call_id="", **_)``
    i.e. Hermes hands us the session id directly → precise, real-time provenance.
  * ``ctx.register_tool(name, toolset, schema, handler, description=...)`` lets us
    expose a ``loom_sync`` tool the user can call from Hermes.

Robustness: this module imports nothing from Hermes and probes ``ctx`` with
``hasattr``/``try`` so it works across versions; every callback is wrapped so an
exception is logged and swallowed — the plugin can never crash Hermes' main flow.
If a hook point is missing, the snapshot-diff + state.db ingest fallbacks (run at
load and on ``on_session_start``) still provide coverage.
"""

from __future__ import annotations

import json
import logging
import threading

from .ledger import Ledger
from .observer import Observer

log = logging.getLogger("hermes_loom.plugin")

PLUGIN_NAME = "hermes-loom"
PLUGIN_VERSION = "0.1.0"

# Hermes tool names we treat as growth signals (verified in the runtime registry).
_MEMORY_TOOL = "memory"
_SKILL_WRITE_TOOL = "skill_manage"   # skill_view is read-only and ignored

_SKILL_ACTION_KIND = {
    "create": "create", "add": "create", "new": "create",
    "edit": "edit", "update": "edit", "write": "edit",
    "patch": "patch",
    "delete": "delete", "remove": "delete", "rm": "delete",
}

LOOM_SYNC_SCHEMA = {
    "name": "loom_sync",
    "description": "Reconcile the Hermes Loom growth ledger with current memory/skills "
                   "(runs state.db ingest + snapshot diff). Returns a small summary.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}


def _safe(fn):
    """Wrap a callback so it can never raise into the Hermes host."""
    def wrapper(*a, **k):
        try:
            return fn(*a, **k)
        except Exception:  # noqa: BLE001
            log.exception("hermes-loom callback failed (degraded, Hermes unaffected)")
            return None
    wrapper.__name__ = getattr(fn, "__name__", "loom_cb")
    return wrapper


def _as_dict(v):
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        try:
            d = json.loads(v)
            return d if isinstance(d, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


class LoomPlugin:
    def __init__(self):
        self.ledger = Ledger()
        self.observer = Observer(self.ledger)

    # -- the one hook that catches memory + skill mutations ------------------
    def on_post_tool_call(self, *, tool_name="", args=None, result=None,
                          session_id="", tool_call_id="", **_):
        if tool_name == _MEMORY_TOOL:
            self._record_memory(args, result, session_id, tool_call_id)
        elif tool_name == _SKILL_WRITE_TOOL:
            self._record_skill(args, result, session_id, tool_call_id)

    def _record_memory(self, args, result, session_id, tool_call_id):
        a = _as_dict(args)
        res = _as_dict(result)
        if res.get("success") is False:
            return  # the tool call failed; nothing actually changed
        action = a.get("action", "add")
        target = a.get("target", "memory")
        content = a.get("content") or a.get("text")
        self.observer.on_memory_write(
            action, target, content,
            session_id=session_id or None,
            source_hint="plugin_hook",
            tool_name=_MEMORY_TOOL,
            metadata={"tool_call_id": tool_call_id, "result": res.get("message")},
        )

    def _record_skill(self, args, result, session_id, tool_call_id):
        a = _as_dict(args)
        res = _as_dict(result)
        if res.get("success") is False:
            return
        raw_action = (a.get("action") or "edit").lower()
        action = _SKILL_ACTION_KIND.get(raw_action, "edit")
        skill_name = a.get("skill_name") or a.get("name") or a.get("skill") or "unknown"
        content = a.get("skill_md") or a.get("content") or a.get("body")
        self.observer.on_skill_write(
            action, skill_name, content=content,
            session_id=session_id or None,
            source_hint="plugin_hook",
            tool_name=_SKILL_WRITE_TOOL,
            metadata={"tool_call_id": tool_call_id, "result": res.get("message")},
        )

    # -- context injection before the model call -----------------------------
    def on_pre_llm_call(self, *, user_message="", **_kw):
        """Read the user's message, resolve relevant tags (AI/keyword), and
        inject matching tagged records as context. Returns {"context": ...} or None.
        """
        msg = user_message if isinstance(user_message, str) else (
            user_message.get("content") if isinstance(user_message, dict) else "")
        if not msg:
            return None
        from . import service
        res = service.recall(self.ledger, msg)
        if res.get("context"):
            return {"context": res["context"]}
        return None

    # -- startup safety net --------------------------------------------------
    def on_session_start(self, *_a, **_k):
        from . import snapshot
        snapshot.bootstrap(self.ledger)
        snapshot.reconcile_all(self.ledger)

    # -- user-invokable tool -------------------------------------------------
    def loom_sync_tool(self, **_kwargs):
        from . import ingest, snapshot
        rec = snapshot.reconcile_all(self.ledger)
        ing = ingest.ingest_state_db(self.ledger)
        return {"reconcile": {k: len(v) for k, v in rec.items()}, "ingest": ing}


def register(ctx):
    """Hermes plugin entrypoint. Binds the real hooks; degrades if absent."""
    plugin = LoomPlugin()
    bound = []

    if _register_hook(ctx, "post_tool_call", _safe(plugin.on_post_tool_call)):
        bound.append("post_tool_call")
    if _register_hook(ctx, "pre_llm_call", _safe(plugin.on_pre_llm_call)):
        bound.append("pre_llm_call")
    if _register_hook(ctx, "on_session_start", _safe(plugin.on_session_start)):
        bound.append("on_session_start")

    _register_tool(ctx, plugin)

    # Run the fallback once at load (background) so coverage is immediate even if
    # no hooks were bindable on this Hermes build.
    threading.Thread(target=_safe(plugin.on_session_start), daemon=True).start()

    log.info("hermes-loom registered (hooks: %s)", bound or "none — fallback only")
    return {"name": PLUGIN_NAME, "version": PLUGIN_VERSION, "hooks": bound}


def _register_hook(ctx, name, cb) -> bool:
    reg = getattr(ctx, "register_hook", None)
    if not callable(reg):
        return False
    try:
        reg(name, cb)
        return True
    except Exception:  # noqa: BLE001 - hook point may be unavailable; that's fine
        log.debug("could not bind hook %s", name, exc_info=True)
        return False


def _register_tool(ctx, plugin):
    reg = getattr(ctx, "register_tool", None)
    if not callable(reg):
        return
    try:
        reg(
            name="loom_sync",
            toolset="loom",
            schema=LOOM_SYNC_SCHEMA,
            handler=_safe(plugin.loom_sync_tool),
            description=LOOM_SYNC_SCHEMA["description"],
        )
    except Exception:  # noqa: BLE001
        log.debug("could not register loom_sync tool", exc_info=True)
