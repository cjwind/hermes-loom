"""Backfill precise growth events from the Hermes session store (state.db).

Hermes records every tool call in ``messages``. Memory writes appear as a
``memory`` tool call whose assistant-side ``tool_calls`` carry
``{"action","target","content"}`` and whose tool-result row confirms success.
That is *exact* provenance: real session id, real timestamp, and the conversation
window around it — no guessing.

This path runs fully offline against state.db and is what makes "see what Hermes
grew and roughly where it came from" work even before the live plugin is wired
in. It is idempotent via a dedup key per tool call id.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from . import hermes_state, provenance
from .ledger import Ledger

log = logging.getLogger("hermes_loom.ingest")

_MEMORY_TOOLS = {"memory"}
# Skill mutation tools (read-only ones like skill_view are ignored).
_SKILL_WRITE_TOOLS = {
    "skill_create", "skill_edit", "skill_patch", "skill_delete",
    "skill_write", "skill_update", "skill_remove",
}
_SKILL_KIND = {
    "create": "skill_created", "write": "skill_created",
    "patch": "skill_patched", "edit": "skill_edited", "update": "skill_edited",
    "delete": "skill_deleted", "remove": "skill_deleted",
}


def _iter_tool_calls(conn):
    """Yield (msg_id, session_id, ts, call_id, fn_name, arguments) per tool call."""
    rows = conn.execute(
        "SELECT id, session_id, timestamp, tool_calls FROM messages "
        "WHERE tool_calls IS NOT NULL AND tool_calls != '' ORDER BY id ASC"
    ).fetchall()
    for r in rows:
        try:
            calls = json.loads(r["tool_calls"])
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(calls, list):
            continue
        for c in calls:
            fn = (c.get("function") or {}) if isinstance(c, dict) else {}
            name = fn.get("name")
            if not name:
                continue
            call_id = c.get("call_id") or c.get("id")
            yield r["id"], r["session_id"], r["timestamp"], call_id, name, fn.get("arguments")


def _result_for(conn, call_id: str) -> Optional[dict]:
    if not call_id:
        return None
    row = conn.execute(
        "SELECT content FROM messages WHERE tool_call_id=? ORDER BY id ASC LIMIT 1",
        (call_id,),
    ).fetchone()
    if not row or not row["content"]:
        return None
    try:
        return json.loads(row["content"])
    except (json.JSONDecodeError, TypeError):
        return None


def ingest_state_db(ledger: Ledger, *, only_session: Optional[str] = None) -> dict:
    """Scan state.db for memory/skill tool calls and record growth events."""
    conn = hermes_state._connect_ro()  # noqa: SLF001
    if not conn:
        return {"available": False, "memory_events": 0, "skill_events": 0}

    mem_n = skill_n = 0
    try:
        for msg_id, session_id, ts, call_id, name, args_raw in _iter_tool_calls(conn):
            if only_session and session_id != only_session:
                continue
            is_mem = name in _MEMORY_TOOLS
            is_skill = name in _SKILL_WRITE_TOOLS
            if not (is_mem or is_skill):
                continue

            dedup = f"statedb:{call_id or msg_id}"
            if ledger.event_exists(dedup):
                continue

            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
            except (json.JSONDecodeError, TypeError):
                args = {}
            result = _result_for(conn, call_id)

            window = provenance.capture_session_window(ledger, session_id, around_ts=ts)
            meta = {"dedup": dedup, "msg_id": msg_id, "source": "statedb_ingest"}
            if result and isinstance(result, dict):
                meta["result_message"] = result.get("message")
                if result.get("success") is False:
                    meta["failed"] = True

            if is_mem:
                action = args.get("action", "add")
                target = args.get("target", "memory")
                content = args.get("content") or args.get("text")
                ledger.add_event(
                    kind=_mem_kind(action), target_type=("user" if target == "user" else "memory"),
                    action=action, after_text=content,
                    source_session_id=session_id, source_message_window=window,
                    source_hint="statedb_ingest", tool_name=name, timestamp=ts, metadata=meta,
                )
                mem_n += 1
            else:
                action = args.get("action") or name.replace("skill_", "")
                skill_name = args.get("name") or args.get("skill") or "unknown"
                content = args.get("content") or args.get("body")
                # We pass the precomputed window straight to the ledger so the
                # observer doesn't re-query state.db.
                ledger.add_event(
                    kind=_SKILL_KIND.get(action, "skill_edited"), target_type="skill",
                    action=action, target_key=skill_name, after_text=content,
                    before_text=None, source_session_id=session_id,
                    source_message_window=window, source_hint="statedb_ingest",
                    tool_name=name, timestamp=ts, metadata=meta,
                )
                skill_n += 1
        return {"available": True, "memory_events": mem_n, "skill_events": skill_n}
    finally:
        conn.close()


def _mem_kind(action: str) -> str:
    a = (action or "").lower()
    if a in ("remove", "delete"):
        return "memory_removed"
    if a in ("replace", "update", "edit"):
        return "memory_replaced"
    return "memory_added"
