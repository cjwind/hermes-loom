"""Hermes plugin — the live observation entrypoint.

Hermes loads plugins and calls ``register(ctx)``. We use the documented surface
(``ctx.register_tool`` / ``ctx.register_hook`` and the memory-provider
``on_memory_write`` concept) to observe memory/skill mutations in real time and
forward them to the Loom ledger.

IMPORTANT — graceful degradation:
  * This module imports nothing from Hermes. It only *uses* whatever ``ctx``
    offers, guarded by ``hasattr`` / ``try`` so it works across Hermes versions
    and never crashes the host. If a hook point is unavailable, we register what
    we can and rely on the state.db ingest + snapshot-diff fallback (run on a
    timer / at startup) to fill the gap.
  * Every callback is wrapped so an exception is logged and swallowed — the
    plugin can fail without taking down Hermes' main flow (Part 4 requirement).

Hooks we attempt to bind (names are matched leniently against what ctx exposes):
  * memory write   -> on_memory_write(action, target, content)
  * tool post-call -> to catch skill_create/edit/patch/delete tool results
  * session start  -> opportunistic reconcile/ingest
"""

from __future__ import annotations

import logging
import os
import threading

from .ledger import Ledger
from .observer import Observer

log = logging.getLogger("hermes_loom.plugin")

PLUGIN_NAME = "hermes-loom"
PLUGIN_VERSION = "0.1.0"

# Hermes-side memory/skill tool names we treat as mutations.
_SKILL_WRITE_TOOLS = {
    "skill_create", "skill_edit", "skill_patch", "skill_delete",
    "skill_write", "skill_update", "skill_remove",
}
_SKILL_ACTION_BY_TOOL = {
    "skill_create": "create", "skill_write": "create",
    "skill_edit": "edit", "skill_update": "edit",
    "skill_patch": "patch",
    "skill_delete": "delete", "skill_remove": "delete",
}


def _safe(fn):
    """Wrap a callback so it can never raise into the Hermes host."""
    def wrapper(*a, **k):
        try:
            return fn(*a, **k)
        except Exception:  # noqa: BLE001
            log.exception("hermes-loom callback failed (degraded, Hermes unaffected)")
            return None
    return wrapper


class LoomPlugin:
    def __init__(self):
        self.ledger = Ledger()
        self.observer = Observer(self.ledger)

    # -- memory provider hook -----------------------------------------------
    def on_memory_write(self, action, target, content, **extra):
        """Memory-provider style hook. ``extra`` may carry session_id/before."""
        self.observer.on_memory_write(
            action, target, content,
            before_text=extra.get("before") or extra.get("before_text"),
            session_id=extra.get("session_id") or _current_session(extra),
            source_hint="plugin_hook",
            tool_name="memory",
        )

    # -- generic post-tool hook ---------------------------------------------
    def on_tool_call(self, event):
        """Catch skill mutations from a tool post-call hook.

        ``event`` is treated as a mapping/object exposing name + arguments +
        session id. We read defensively to survive schema differences.
        """
        name = _get(event, "tool_name") or _get(event, "name")
        if name not in _SKILL_WRITE_TOOLS:
            return
        args = _get(event, "arguments") or _get(event, "args") or {}
        if isinstance(args, str):
            import json
            try:
                args = json.loads(args)
            except Exception:  # noqa: BLE001
                args = {}
        skill_name = args.get("name") or args.get("skill") or "unknown"
        action = _SKILL_ACTION_BY_TOOL.get(name, "edit")
        self.observer.on_skill_write(
            action, skill_name,
            content=args.get("content") or args.get("body"),
            session_id=_get(event, "session_id"),
            tool_name=name,
            source_hint="plugin_hook",
        )

    # -- startup safety net --------------------------------------------------
    def on_session_start(self, *_a, **_k):
        """Opportunistically run the fallback so we never silently miss growth."""
        from . import snapshot
        snapshot.bootstrap(self.ledger)
        snapshot.reconcile_all(self.ledger)


def _current_session(extra):
    return extra.get("session") or os.environ.get("HERMES_SESSION_ID")


def _get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def register(ctx):
    """Hermes plugin entrypoint.

    We bind to whatever hook points ``ctx`` exposes. Unknown points are skipped
    (logged), and the snapshot-diff + state.db ingest fallbacks cover the rest.
    """
    plugin = LoomPlugin()
    bound = []

    # 1) Memory-provider style hook
    for hook_name in ("memory_write", "on_memory_write", "memory.write"):
        if _try_register_hook(ctx, hook_name, _safe(plugin.on_memory_write)):
            bound.append(hook_name)
            break

    # 2) Post tool-call hook (for skills + as a memory backstop)
    for hook_name in ("tool_post", "post_tool_call", "after_tool_call", "tool_call"):
        if _try_register_hook(ctx, hook_name, _safe(plugin.on_tool_call)):
            bound.append(hook_name)
            break

    # 3) Session start -> run fallback
    for hook_name in ("session_start", "on_session_start"):
        if _try_register_hook(ctx, hook_name, _safe(plugin.on_session_start)):
            bound.append(hook_name)
            break

    # 4) Expose a manual tool so the user can trigger a Loom sync from Hermes.
    _try_register_tool(ctx, plugin)

    # Always run the fallback once at load, in the background, so coverage is
    # immediate even if zero hooks were bindable on this Hermes version.
    threading.Thread(target=_safe(plugin.on_session_start), daemon=True).start()

    log.info("hermes-loom registered (hooks bound: %s)", bound or "none — fallback only")
    return {"name": PLUGIN_NAME, "version": PLUGIN_VERSION, "hooks": bound}


def _try_register_hook(ctx, name, cb) -> bool:
    reg = getattr(ctx, "register_hook", None)
    if not callable(reg):
        return False
    try:
        reg(name, cb)
        return True
    except Exception:  # noqa: BLE001 - this hook point may not exist; that's fine
        return False


def _try_register_tool(ctx, plugin):
    reg = getattr(ctx, "register_tool", None)
    if not callable(reg):
        return
    def loom_sync(**_kwargs):
        from . import snapshot, ingest
        r1 = snapshot.reconcile_all(plugin.ledger)
        r2 = ingest.ingest_state_db(plugin.ledger)
        return {"reconcile": {k: len(v) for k, v in r1.items()}, "ingest": r2}
    try:
        reg("loom_sync", _safe(loom_sync),
            description="Hermes Loom: reconcile growth ledger with current memory/skills.")
    except Exception:  # noqa: BLE001
        pass
