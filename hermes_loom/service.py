"""Service layer — assembles API responses from the ledger + Hermes native state.

Keeps the HTTP layer (api.py) thin and lets tests call business logic directly.
This layer is the only place the three domains are *joined* (events from the
ledger, live content from Hermes, provenance from state.db).
"""

from __future__ import annotations

import time
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


def auto_deposit_status(ledger: Ledger) -> dict:
    """Real status for the header pill: is Hermes' auto-deposit observable?

    Combines three signals:
      * plugin installed + enabled (from Hermes' own config.yaml)
      * gateway running (gateway_state.json) — Hermes' auto-deposit needs it
      * recent live observation (a plugin_hook event in the ledger)

    state ∈ {live, enabled, offline}:
      * live    — gateway running AND plugin enabled
      * enabled — plugin enabled but gateway not confirmed running
      * offline — plugin not installed/enabled
    """
    plug = hermes_state.plugin_status()
    gw = hermes_state.gateway_status()
    last_hook = ledger.conn.execute(
        "SELECT timestamp FROM growth_events WHERE source_hint='plugin_hook' "
        "ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    last_hook_ts = last_hook[0] if last_hook else None

    if plug["installed"] and plug["enabled"]:
        state = "live" if gw["running"] else "enabled"
    else:
        state = "offline"

    label = {
        "live": "自動沉澱進行中",
        "enabled": "plugin 已啟用，等待沉澱",
        "offline": "plugin 未啟用",
    }[state]
    return {
        "state": state, "label": label,
        "plugin": plug, "gateway": gw,
        "last_plugin_hook": last_hook_ts,
        "last_plugin_hook_rel": _rel_time(last_hook_ts) if last_hook_ts else None,
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


# ===========================================================================
# Inspector "records" — aggregate real growth into the design's Record model.
# A record = a live memory/user entry (or a skill), with its event history as
# versions and its originating session as provenance. See ui/ (Inspector).
# ===========================================================================

# Loom-side category defaults (Hermes has no categories; reclassify overrides).
_CAT_DEFAULT = {"memory": "memory", "user": "pref", "skill": "skill"}
_HINT_CONF = {"plugin_hook": 3, "statedb_ingest": 3, "manual_override": 3,
              "snapshot_diff": 2, "bootstrap": 1}
_HINT_LABEL = {
    "plugin_hook": "即時由 plugin 觀測到", "statedb_ingest": "從 session 紀錄精準回填",
    "snapshot_diff": "由快照比對推測", "bootstrap": "安裝前既有，匯入為歷史",
    "manual_override": "你的人工調整",
}


def _rel_time(ts: Optional[float]) -> str:
    if not ts:
        return ""
    d = time.time() - ts
    if d < 90:
        return "剛剛"
    if d < 3600:
        return f"{int(d // 60)} 分鐘前"
    if d < 86400:
        return f"{int(d // 3600)} 小時前"
    if d < 86400 * 30:
        return f"{int(d // 86400)} 天前"
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def _origin_event(ledger: Ledger, target_type: str, value: str) -> Optional[dict]:
    """The (most recent) growth event whose after_text == value — gives the
    originating session + message window for provenance."""
    if value is None:
        return None
    for e in ledger.query_events(target_type=target_type, limit=800):
        if e["after_text"] == value:
            return e
    return None


def _raw_from_event(ev: Optional[dict]) -> Optional[dict]:
    """Best-effort RAW conversation block from an event's message window."""
    if not ev:
        return None
    win = ev.get("source_message_window") or []
    user_msg = next((m for m in reversed(win) if m.get("role") == "user"), None)
    if not user_msg:
        user_msg = next((m for m in reversed(win)
                         if m.get("role") == "assistant" and m.get("snippet")), None)
    if not user_msg:
        return None
    who = "你" if user_msg.get("role") == "user" else "Hermes"
    return {"who": who, "parts": [user_msg.get("snippet", "")]}


def _state(states: dict, target_type: str, key: str) -> dict:
    return states.get((target_type, key)) or {}


def _build_record(ledger: Ledger, target_type: str, key: str, value: str,
                  states: dict, *, detail: str = "", skill_content: Optional[str] = None) -> dict:
    st = _state(states, target_type, key)
    overrides_list = ledger.overrides_for_target(target_type, key)
    edit_ovr = next((o for o in overrides_list
                     if o["override_type"] == "edit" and o["after_text"] == value), None)

    if edit_ovr and edit_ovr.get("before_text") is not None:
        base = edit_ovr["before_text"]
        origin = _origin_event(ledger, target_type, base) or _origin_event(ledger, target_type, value)
        versions = [
            {"v": "v1", "kind": "auto", "who": "Hermes 自動沉澱",
             "when": _rel_time(origin["timestamp"]) if origin else "", "value": base},
            {"v": "v2", "kind": "human", "who": "你的修改",
             "when": _rel_time(edit_ovr["applied_at"]), "value": value},
        ]
        active = 1
    else:
        origin = _origin_event(ledger, target_type, value)
        versions = [{"v": "v1", "kind": "auto", "who": "Hermes 自動沉澱",
                     "when": _rel_time(origin["timestamp"]) if origin else "", "value": value}]
        active = 0

    hint = origin["source_hint"] if origin else None
    cat = st.get("cat") or _CAT_DEFAULT.get(target_type, "memory")
    if cat not in _CAT_LABELS:   # coerce any legacy category (e.g. fact/struct)
        cat = _CAT_DEFAULT.get(target_type, "memory")
    sess = (origin or {}).get("source_session_id")
    rec = {
        "id": f"{target_type}:{key}",
        "target_type": target_type,
        "target_key": key,
        "cat": cat,
        "detail": detail or (_HINT_LABEL.get(hint, "Hermes 自動沉澱的紀錄")),
        "conf": _HINT_CONF.get(hint, 2),
        "when": _rel_time(origin["timestamp"]) if origin else "",
        "originId": ("session · " + sess[-6:]) if sess else "—",
        "origin": (origin or {}).get("tool_name") or "Hermes",
        "session_id": sess,
        "raw": _raw_from_event(origin) or {"who": "Hermes", "parts": ["（找不到對應的原始對話片段）"]},
        "extract": [value] if value else [],
        "classify": [_cat_label(cat), _HINT_LABEL.get(hint, "由 Hermes 自動歸納")],
        "active": active,
        "versions": versions,
        "pinned": bool(st.get("pinned")),
        "annotation": ({"text": st["annotation"], "when": _rel_time(st.get("annotation_at"))}
                       if st.get("annotation") else None),
        "reclassified": ({"from": st.get("reclass_from"), "to": st.get("reclass_to"),
                          "when": _rel_time(st.get("reclass_at"))}
                         if st.get("reclass_to") else None),
        "origin_event_id": (origin or {}).get("id"),
    }
    if skill_content is not None:
        rec["skill_content"] = skill_content
    return rec


# Loom uses three categories only: 記憶 / 技能 / 偏好. (Hermes has no categories;
# these are a Loom-side organizational layer. memory store → 記憶, user store →
# 偏好, skills → 技能; the user can reclassify among these three.)
_CAT_LABELS = {"memory": "記憶", "skill": "技能", "pref": "偏好"}


def _cat_label(k: str) -> str:
    return _CAT_LABELS.get(k, k)


def build_records(ledger: Ledger) -> dict:
    states = ledger.all_record_states()
    records = []
    for store in ("memory", "user"):
        content = hermes_state.read_memory(store)
        for e in parse_entries(content or ""):
            records.append(_build_record(ledger, store, e["key"], e["text"], states))
    for s in hermes_state.list_skills():
        val = s.get("description") or s["name"]
        records.append(_build_record(
            ledger, "skill", s["name"], val, states,
            detail=f"技能 · {s.get('category') or ''}".strip(" ·")))
    return {"count": len(records), "records": records,
            "cats": [{"k": k, "label": v} for k, v in _CAT_LABELS.items()]}


def record_detail(ledger: Ledger, record_id: str) -> Optional[dict]:
    target_type, _, key = record_id.partition(":")
    states = ledger.all_record_states()
    if target_type in ("memory", "user"):
        content = hermes_state.read_memory(target_type)
        ent = next((e for e in parse_entries(content or "") if e["key"] == key), None)
        if not ent:
            return None
        return _build_record(ledger, target_type, key, ent["text"], states)
    if target_type == "skill":
        full = hermes_state.read_skill(key)
        if not full:
            return None
        val = full.get("description") or key
        return _build_record(ledger, "skill", key, val, states,
                             detail=f"技能 · {full.get('category') or ''}".strip(" ·"),
                             skill_content=full["content"])
    return None


# -- inspector mutations -----------------------------------------------------

def record_edit(ledger: Ledger, target_type: str, key: str, new_value: str, reason=None):
    if target_type in ("memory", "user"):
        return overrides.edit_memory_entry(ledger, target_type, key, new_value, reason=reason)
    if target_type == "skill":
        return overrides.edit_skill(ledger, key, new_value, reason=reason)
    raise overrides.OverrideError(f"unknown target_type {target_type}")


def record_delete(ledger: Ledger, target_type: str, key: str, reason=None):
    if target_type in ("memory", "user"):
        return overrides.delete_memory_entry(ledger, target_type, key, reason=reason)
    if target_type == "skill":
        return overrides.delete_skill(ledger, key, hard=False, reason=reason)
    raise overrides.OverrideError(f"unknown target_type {target_type}")
