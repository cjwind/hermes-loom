"""Service layer — assembles API responses from the ledger + Hermes native state.

Keeps the HTTP layer (api.py) thin and lets tests call business logic directly.
This layer is the only place the three domains are *joined* (events from the
ledger, live content from Hermes, provenance from state.db).
"""

from __future__ import annotations

from typing import Optional

from . import hermes_state, overrides
from .ledger import Ledger
from .memory_parser import parse_entries


def list_events(ledger: Ledger, **filters) -> dict:
    events = ledger.query_events(**filters)
    return {"count": len(events), "events": [_event_summary(e) for e in events]}


def _event_summary(e: dict) -> dict:
    return {
        "id": e["id"],
        "timestamp": e["timestamp"],
        "created_at": e["created_at"],
        "kind": e["kind"],
        "target_type": e["target_type"],
        "target_key": e["target_key"],
        "action": e["action"],
        "source_session_id": e["source_session_id"],
        "source_hint": e["source_hint"],
        "tool_name": e["tool_name"],
        "status": e["status"],
        "historical": bool((e.get("metadata") or {}).get("historical")),
        "inferred": bool((e.get("metadata") or {}).get("inferred")),
        "has_before": e["before_text"] is not None,
        "has_after": e["after_text"] is not None,
    }


def event_detail(ledger: Ledger, event_id: int) -> Optional[dict]:
    e = ledger.get_event(event_id)
    if not e:
        return None
    related = []
    if e["target_key"]:
        related = ledger.overrides_for_target(e["target_type"], e["target_key"])
    session = ledger.get_session(e["source_session_id"]) if e["source_session_id"] else None
    return {
        "event": e,
        "before": e["before_text"],
        "after": e["after_text"],
        "source_session": session,
        "source_message_window": e["source_message_window"],
        "metadata": e["metadata"],
        "related_overrides": related,
    }


def current_memory(ledger: Ledger) -> dict:
    out = {}
    for store_type in ("memory", "user"):
        content = hermes_state.read_memory(store_type)
        out[store_type] = {
            "exists": content is not None,
            "raw": content,
            "entries": parse_entries(content or ""),
        }
    return out


def list_skills(ledger: Ledger) -> dict:
    skills = hermes_state.list_skills()
    result = []
    for s in skills:
        evs = ledger.events_for_target("skill", s["name"])
        last = evs[0] if evs else None
        result.append({
            **{k: s[k] for k in ("name", "category", "description", "tags", "mtime", "path")},
            "event_count": len(evs),
            "last_event": _event_summary(last) if last else None,
        })
    result.sort(key=lambda x: x["mtime"], reverse=True)
    return {"count": len(result), "skills": result}


def skill_detail(ledger: Ledger, name: str) -> Optional[dict]:
    full = hermes_state.read_skill(name)
    if not full:
        return None
    evs = ledger.events_for_target("skill", name)
    return {
        "skill": {k: full[k] for k in ("name", "category", "description", "tags", "path", "content")},
        "events": [_event_summary(e) for e in evs],
        "overrides": ledger.overrides_for_target("skill", name),
    }


def session_context(ledger: Ledger, session_id: str, limit: int = 20) -> dict:
    ctx = hermes_state.get_session_context(session_id, limit=limit)
    ctx["events"] = [_event_summary(e) for e in ledger.query_events(session_id=session_id, limit=100)]
    return ctx


# ----- override entrypoints (thin wrappers, used by API) ---------------------

def apply_memory_edit(ledger: Ledger, store_type: str, entry_key: str, new_text: str, reason=None):
    return overrides.edit_memory_entry(ledger, store_type, entry_key, new_text, reason=reason)


def apply_memory_delete(ledger: Ledger, store_type: str, entry_key: str, reason=None):
    return overrides.delete_memory_entry(ledger, store_type, entry_key, reason=reason)


def apply_skill_edit(ledger: Ledger, name: str, new_content: str, reason=None):
    return overrides.edit_skill(ledger, name, new_content, reason=reason)


def apply_skill_delete(ledger: Ledger, name: str, hard: bool = False, reason=None):
    return overrides.delete_skill(ledger, name, hard=hard, reason=reason)
