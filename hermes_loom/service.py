"""Service layer — assembles API responses from the ledger + Hermes native state.

Keeps the HTTP layer (api.py) thin and lets tests call business logic directly.
This layer is the only place the three domains are *joined* (events from the
ledger, live content from Hermes, provenance from state.db).
"""

from __future__ import annotations

import re
import time
from typing import Optional

from . import hermes_state, overrides, skill_origin
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


# ---- assembled prompt viewer -------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+?)\s*$")


def list_prompts(ledger: Ledger, limit: int = 40) -> dict:
    """Recent conversations whose final assembled system prompt we can show."""
    sessions = hermes_state.recent_sessions_with_prompt(limit)
    return {"count": len(sessions), "sessions": sessions}


def _prompt_outline(text: str) -> list:
    """Extract markdown headings so the UI can offer a jump-to outline."""
    out = []
    for i, line in enumerate(text.splitlines()):
        m = _HEADING_RE.match(line)
        if m:
            out.append({"level": len(m.group(1)), "text": m.group(2), "line": i})
    return out


def prompt_detail(ledger: Ledger, session_id: str) -> Optional[dict]:
    """The full assembled system prompt + metadata + outline for one session."""
    row = hermes_state.get_assembled_prompt(session_id)
    if not row:
        return None
    sp = row["system_prompt"]
    return {
        "session_id": row["id"],
        "title": row.get("title"),
        "source": row.get("source"),
        "model": row.get("model"),
        "started_at": row.get("started_at"),
        "ended_at": row.get("ended_at"),
        "message_count": row.get("message_count"),
        "chars": len(sp),
        "lines": sp.count("\n") + 1,
        "system_prompt": sp,
        "outline": _prompt_outline(sp),
        # the rest of the request: the conversation + what pre_llm_call injected
        "messages": hermes_state.get_session_messages(row["id"]),
        "recalls": ledger.recalls_for_session(row["id"]),
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
            **{k: s[k] for k in ("name", "category", "description", "tags", "mtime", "path",
                                 "is_agent_created", "origin_type", "author")},
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
        "skill": {k: full[k] for k in ("name", "category", "description", "tags", "path", "content",
                                       "is_agent_created", "origin_type", "author")},
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
# Known provenance hints. The UI renders the human-readable label from the
# "hint.<hint>" i18n key, so the backend only emits the stable hint string.
_KNOWN_HINTS = set(_HINT_CONF)


def _who_key(human: bool, hint: Optional[str] = None) -> str:
    """i18n key for a version's authorship. Manual edits → 'who.you'; auto
    deposits carry their provenance hint ('hint.<hint>') when known, else a
    generic 'who.hermesAuto'."""
    if human:
        return "who.you"
    return ("hint." + hint) if hint in _KNOWN_HINTS else "who.hermesAuto"


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
    who = "who.user" if user_msg.get("role") == "user" else "who.hermes"
    return {"who": who, "parts": [user_msg.get("snippet", "")]}


def _state(states: dict, target_type: str, key: str) -> dict:
    return states.get((target_type, key)) or {}


# --- source trace / provenance -----------------------------------------------
# How well can we trace a record back to where it came from? Rather than a
# binary "found / not found", classify into states the UI can explain and that
# carry an honest confidence.
#
#   exact_match  — a precise originating conversation snippet exists
#   window_match — no precise snippet, but the session window is available
#   imported     — pre-existed Loom; came in via bootstrap/snapshot import
#   external     — a non-conversation source (manual edit, Hermes runtime file)
#   inferred     — system-inferred (snapshot diff), rough origin only
#   missing      — a source was expected but cannot be located
_TRACE_CONFIDENCE = {
    "exact_match": "high", "window_match": "medium", "imported": "medium",
    "external": "medium", "inferred": "low", "missing": "low",
}
# i18n key naming why this isn't an exact match (None for exact_match).
_TRACE_FALLBACK = {
    "window_match": "fallback.window", "imported": "fallback.imported",
    "external": "fallback.external", "inferred": "fallback.inferred",
    "missing": "fallback.missing",
}
# Coarse origin kind, so the UI can keep runtime / import / external distinct.
_TRACE_OBSERVED = {
    "exact_match": "runtime", "window_match": "runtime", "imported": "import",
    "external": "external", "inferred": "inferred", "missing": "none",
}


def _bootstrap_held_value(ledger: Ledger, target_type: str, value: str) -> bool:
    """True if a bootstrap snapshot-import for this store already contained this
    value — i.e. the entry pre-dates Loom and arrived via import, not a deposit.
    (Bootstrap events store the whole file, so we substring-match the entry.)"""
    if not value:
        return False
    evs = ledger.query_events(target_type=target_type, kind="memory_snapshot_imported", limit=3)
    needle = value.strip()
    return any(needle and needle in (e.get("after_text") or "") for e in evs)


def _source_trace(ledger: Ledger, target_type: str, key: str, value: str,
                  origin: Optional[dict], *, skill_meta: Optional[dict] = None,
                  deep: bool = False) -> dict:
    """Provenance summary for a record. ``origin`` is the value-matched event
    (precise for memory/user). Skills store SKILL.md *content* in their events,
    not the description we key on, so we resolve their trace by skill name.

    ``deep`` additionally resolves the session title, snippet text and window
    (extra DB reads) — used by the detail view, skipped by the list view."""
    prov = origin
    if prov is None and target_type == "skill":
        evs = ledger.events_for_target("skill", key)
        prov = next((e for e in evs if e.get("source_session_id")), None) or (evs[0] if evs else None)

    hint = prov.get("source_hint") if prov else None
    raw = _raw_from_event(prov)
    has_snippet = raw is not None
    window = (prov or {}).get("source_message_window") or None
    has_window = bool(window)
    session_id = (prov or {}).get("source_session_id")

    if prov is None:
        if target_type == "skill":
            ot = (skill_meta or {}).get("origin_type")
            # Official / community skills are Hermes/external files, not deposits.
            status = "external" if ot in ("hermes_official", "community") else "missing"
        else:
            status = "imported" if _bootstrap_held_value(ledger, target_type, value) else "missing"
    elif hint == "bootstrap":
        status = "imported"
    elif hint == "manual_override":
        status = "external"
    elif hint == "snapshot_diff":
        status = "inferred"
    elif hint in ("plugin_hook", "statedb_ingest"):
        status = ("exact_match" if has_snippet
                  else "window_match" if (has_window or session_id) else "inferred")
    else:
        status = "inferred"

    traced = status in ("exact_match", "window_match")
    out = {
        "status": status,
        "confidence": _TRACE_CONFIDENCE[status],
        "session_id": session_id,
        "hint": hint,
        "origin_type": (skill_meta or {}).get("origin_type") if target_type == "skill" else None,
        "has_snippet": has_snippet,
        "has_window": has_window,
        "imported": status == "imported",
        "observed": _TRACE_OBSERVED[status],
        "last_traced_at": (prov.get("timestamp") if (prov and traced) else None),
        "fallback_reason": _TRACE_FALLBACK.get(status),
        "summary_key": "provenance.summary." + status,
    }
    if deep:
        sess = ledger.get_session(session_id) if session_id else None
        out["session_title"] = (sess or {}).get("title")
        out["snippet"] = raw["parts"][0] if (raw and raw.get("parts")) else None
        out["snippet_who"] = raw["who"] if raw else None
        out["window"] = window
    return out


def _build_record(ledger: Ledger, target_type: str, key: str, value: str,
                  states: dict, *, detail_key: Optional[str] = None,
                  detail_params: Optional[dict] = None,
                  skill_content: Optional[str] = None,
                  skill_meta: Optional[dict] = None,
                  fallback_ts: float = 0.0, deep: bool = False) -> dict:
    st = _state(states, target_type, key)
    overrides_list = ledger.overrides_for_target(target_type, key)
    edit_ovr = next((o for o in overrides_list
                     if o["override_type"] == "edit" and o["after_text"] == value), None)

    if edit_ovr and edit_ovr.get("before_text") is not None:
        base = edit_ovr["before_text"]
        origin = _origin_event(ledger, target_type, base) or _origin_event(ledger, target_type, value)
        versions = [
            {"v": "v1", "kind": "auto", "who": "who.hermesAuto",
             "whenTs": origin["timestamp"] if origin else None, "value": base},
            {"v": "v2", "kind": "human", "who": "who.you",
             "whenTs": edit_ovr["applied_at"], "value": value},
        ]
        active = 1
    else:
        origin = _origin_event(ledger, target_type, value)
        versions = [{"v": "v1", "kind": "auto", "who": "who.hermesAuto",
                     "whenTs": origin["timestamp"] if origin else None, "value": value}]
        active = 0

    # Sortable timestamp = most recent activity: a manual edit if present, else
    # the originating event, else a caller-supplied fallback (e.g. skill mtime).
    if edit_ovr:
        ts = edit_ovr["applied_at"]
    elif origin:
        ts = origin["timestamp"]
    else:
        ts = fallback_ts

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
        # Display strings are i18n keys + params; the UI renders them. Default
        # detail = the provenance hint's label, else a generic "auto record".
        "detailKey": detail_key or (("hint." + hint) if hint in _KNOWN_HINTS else "detail.autoRecord"),
        "detailParams": detail_params or {},
        "conf": _HINT_CONF.get(hint, 2),
        # Prefer the originating event's time; fall back to the record's sortable
        # ts (e.g. a skill's file mtime) so skills/snapshots still show a time.
        # The UI formats whenTs into a localized relative time.
        "whenTs": (origin["timestamp"] if origin else ts) or None,
        "originId": ("session · " + sess[-6:]) if sess else None,
        "origin": (origin or {}).get("tool_name") or "Hermes",
        "session_id": sess,
        "raw": _raw_from_event(origin) or {"who": "who.hermes", "parts": [], "placeholderKey": "raw.notFound"},
        # Note: the design dropped the EXTRACT/CLASSIFY pipeline stages, so we no
        # longer emit `extract`/`classify`. The category is carried by `cat`.
        "ts": ts,
        "active": active,
        "versions": versions,
        "pinned": bool(st.get("pinned")),
        "annotation": ({"text": st["annotation"], "whenTs": st.get("annotation_at")}
                       if st.get("annotation") else None),
        "reclassified": ({"from": st.get("reclass_from"), "to": st.get("reclass_to"),
                          "whenTs": st.get("reclass_at")}
                         if st.get("reclass_to") else None),
        "origin_event_id": (origin or {}).get("id"),
        # Source-trace status + confidence so the UI can show *how well* this
        # record is traced, not just whether a snippet was found.
        "provenance": _source_trace(ledger, target_type, key, value, origin,
                                    skill_meta=skill_meta, deep=deep),
    }
    if skill_content is not None:
        rec["skill_content"] = skill_content
    return rec


# Loom categories: 記憶→MEMORY.md, 偏好→USER.md, 技能→skills, 暫存(HOLD)→Loom-only
# (not compiled to any file). Hermes itself has no categories; these are Loom-side.
_CAT_LABELS = {"memory": "記憶", "skill": "技能", "pref": "偏好", "hold": "暫存"}


def _build_held_record(h: dict, states: dict) -> dict:
    """Build a Record for a HOLD (Loom-only) entry."""
    key, text = h["key"], h["text"]
    st = _state(states, "hold", key)
    from_label = {"memory": "MEMORY.md", "user": "USER.md"}.get(h.get("from_store"), "?")
    return {
        "id": f"hold:{key}", "target_type": "hold", "target_key": key, "cat": "hold",
        "detailKey": "detail.held", "detailParams": {"from": from_label},
        "conf": 2, "whenTs": h.get("held_at"),
        "originId": None, "origin": "loom", "session_id": h.get("source_session_id"),
        "raw": {"who": "who.user", "parts": [], "placeholderKey": "raw.held"},
        "ts": h.get("held_at") or 0,
        "active": 0,
        "versions": [{"v": "v1", "kind": "human", "who": "who.youHeld", "whenTs": h.get("held_at"), "value": text}],
        "pinned": bool(st.get("pinned")),
        "annotation": ({"text": st["annotation"], "whenTs": st.get("annotation_at")}
                       if st.get("annotation") else None),
        "from_store": h.get("from_store"),
        "held": True,
        # HOLD entries are a Loom-only staging area you parked by hand — a
        # deliberate, non-conversation source.
        "provenance": {
            "status": "external", "confidence": "medium",
            "session_id": h.get("source_session_id"), "hint": "manual_override",
            "origin_type": None, "has_snippet": False, "has_window": False,
            "imported": False, "observed": "external", "last_traced_at": None,
            "fallback_reason": "fallback.external", "summary_key": "provenance.summary.external",
            "session_title": None, "snippet": None, "snippet_who": None, "window": None,
        },
    }


def _skill_version_history(ledger: Ledger, name: str, current_content: str) -> list[dict]:
    """Full content timeline for a skill, oldest→newest, for the diff viewer.

    Sourced from skill_snapshots (each holds the full SKILL.md at one captured
    state). Consecutive identical-content snapshots are collapsed. Each version
    is labelled from its originating event's provenance. The live file content is
    appended as the newest version if it isn't already the last snapshot (e.g. an
    offline edit not yet reconciled), so the viewer always reflects the file."""
    history: list[dict] = []
    prev_hash = None
    for s in ledger.list_skill_snapshots(name):
        if s["content_hash"] == prev_hash:
            continue
        prev_hash = s["content_hash"]
        ev = ledger.get_event(s["source_event_id"]) if s.get("source_event_id") else None
        hint = ev["source_hint"] if ev else None
        human = hint == "manual_override"
        history.append({
            "kind": "human" if human else "auto",
            "who": _who_key(human, hint),
            "whenTs": s["captured_at"],
            "value": s["content"] or "",
        })

    cur = current_content or ""
    if not history or history[-1]["value"] != cur:
        history.append({"kind": "auto", "who": "who.currentFile", "whenTs": None, "value": cur})

    for i, h in enumerate(history):
        h["v"] = f"v{i + 1}"
    return history


def _memory_version_history(
    ledger: Ledger, target_type: str, key: str, current_value: str
) -> list[dict]:
    """Reconstruct a single memory/user entry's full edit chain, oldest→newest.

    Memory entries are addressed by a content-hash key, so every edit changes the
    key. Each ``memory_replaced`` event — whether an auto ``snapshot_diff`` or a
    manual override — records ``metadata.prev_key`` linking the new key back to
    the one it replaced, plus the before/after text. Following that chain
    backwards from the current entry rebuilds every state it passed through,
    giving memory the same full-history view skills already get from snapshots.

    Returns ``{v,kind,who,whenTs,value}`` dicts oldest→newest (who is an i18n key,
    whenTs an epoch the UI formats), or ``[]`` when the entry has no recorded edits
    (the caller then keeps the single-version record).
    """
    events = ledger.query_events(target_type=target_type, limit=2000)  # newest first
    by_key: dict = {}
    for e in events:
        by_key.setdefault(e["target_key"], []).append(e)

    def _producing(k, val):
        """The event that set value ``val`` under key ``k`` (prefer an exact
        text match, else the newest event for that key)."""
        cands = by_key.get(k, [])
        return next((e for e in cands if e["after_text"] == val), None) or (cands[0] if cands else None)

    cur = next((e for e in events
                if e["target_key"] == key and e["after_text"] == current_value), None)
    if cur is None:
        cur = next((e for e in events if e["after_text"] == current_value), None)
    if cur is None:
        return []

    chain: list[dict] = []  # events, newest→oldest
    seen: set = set()
    while cur is not None and cur["id"] not in seen:
        seen.add(cur["id"])
        chain.append(cur)
        prev_key = (cur.get("metadata") or {}).get("prev_key")
        prev_val = cur["before_text"]
        if not prev_key and prev_val is None:
            break
        nxt = _producing(prev_key, prev_val) if prev_key else None
        if nxt is None and prev_val is not None:
            nxt = next((e for e in events if e["after_text"] == prev_val), None)
        cur = nxt
    chain.reverse()  # oldest→newest

    def _ver(ev: dict, value: str) -> dict:
        hint = ev["source_hint"]
        human = (ev["action"] or "").startswith("manual") or hint == "manual_override"
        return {"kind": "human" if human else "auto",
                "who": _who_key(human, hint),
                "whenTs": ev["timestamp"], "value": value}

    versions: list[dict] = []
    # The oldest event's before_text is a prior state with no owning event of its
    # own (e.g. the value at bootstrap). Surface it as the first version, tagged
    # from whichever event originally produced it, if any.
    first = chain[0]
    if first["before_text"]:
        origin = _origin_event(ledger, target_type, first["before_text"])
        versions.append({
            "kind": "auto",
            "who": _who_key(False, origin["source_hint"] if origin else None),
            "whenTs": origin["timestamp"] if origin else None,
            "value": first["before_text"],
        })
    for ev in chain:
        if ev["after_text"] is not None:
            versions.append(_ver(ev, ev["after_text"]))

    # Collapse consecutive identical values (keep the latest provenance for one).
    collapsed: list[dict] = []
    for v in versions:
        if collapsed and collapsed[-1]["value"] == v["value"]:
            collapsed[-1] = v
            continue
        collapsed.append(v)

    if len(collapsed) < 2:
        return []
    for i, v in enumerate(collapsed):
        v["v"] = f"v{i + 1}"
    return collapsed


def _tag_skill_origin(rec: dict, skill: dict) -> dict:
    """Attach origin classification (from the loader) onto a skill record."""
    rec["is_agent_created"] = skill.get("is_agent_created", False)
    rec["origin_type"] = skill.get("origin_type", "community")
    rec["origin_label"] = skill_origin.ORIGIN_LABELS.get(rec["origin_type"], rec["origin_type"])
    rec["author"] = skill.get("author")
    return rec


def _skill_detail(category: Optional[str]):
    """(detailKey, detailParams) for a skill record's subtitle."""
    category = (category or "").strip()
    if category:
        return "detail.skill", {"category": category}
    return "detail.skillNoCat", {}


def build_records(ledger: Ledger) -> dict:
    states = ledger.all_record_states()
    records = []
    for store in ("memory", "user"):
        content = hermes_state.read_memory(store)
        for e in parse_entries(content or ""):
            records.append(_build_record(ledger, store, e["key"], e["text"], states))

    skills = hermes_state.list_skills()
    skill_summary = {"total": len(skills), "agent_created": 0,
                     "hermes_official": 0, "community": 0}
    for s in skills:
        skill_summary[s.get("origin_type", "community")] = \
            skill_summary.get(s.get("origin_type", "community"), 0) + 1
        val = s.get("description") or s["name"]
        dk, dp = _skill_detail(s.get("category"))
        rec = _build_record(ledger, "skill", s["name"], val, states,
                            detail_key=dk, detail_params=dp, skill_meta=s,
                            fallback_ts=s.get("mtime", 0.0))
        records.append(_tag_skill_origin(rec, s))

    for h in ledger.list_held():
        records.append(_build_held_record(h, states))

    # Newest first. The rail claims "依時間", so order really is by ts desc.
    records.sort(key=lambda r: r.get("ts") or 0, reverse=True)

    return {"count": len(records), "records": records,
            "cats": [{"k": k, "label": v} for k, v in _CAT_LABELS.items()],
            "skill_summary": skill_summary}


def record_detail(ledger: Ledger, record_id: str) -> Optional[dict]:
    target_type, _, key = record_id.partition(":")
    states = ledger.all_record_states()
    rec = None
    if target_type in ("memory", "user"):
        content = hermes_state.read_memory(target_type)
        ent = next((e for e in parse_entries(content or "") if e["key"] == key), None)
        if ent:
            rec = _build_record(ledger, target_type, key, ent["text"], states, deep=True)
            # Detail view shows the entry's *full* edit chain (auto + manual),
            # reconstructed from the prev_key links — not just current-vs-previous.
            # Kept out of build_records (list view) to avoid a full event scan per
            # entry; only the opened record pays for it.
            hist = _memory_version_history(ledger, target_type, key, ent["text"])
            if len(hist) >= 2:
                rec["versions"] = hist
                rec["active"] = next(
                    (i for i, v in enumerate(hist) if v["value"] == ent["text"]),
                    len(hist) - 1,
                )
    elif target_type == "skill":
        full = hermes_state.read_skill(key)
        if full:
            val = full.get("description") or key
            dk, dp = _skill_detail(full.get("category"))
            rec = _build_record(ledger, "skill", key, val, states,
                                detail_key=dk, detail_params=dp,
                                skill_content=full["content"], skill_meta=full, deep=True)
            rec["skill_versions"] = _skill_version_history(ledger, key, full["content"])
            rec = _tag_skill_origin(rec, full)
    elif target_type == "hold":
        h = ledger.get_held(key)
        rec = _build_held_record(h, states) if h else None
    return rec


def _active_value(r: dict) -> str:
    return r["versions"][r["active"]]["value"]


# ---- packs (Loom-only middle memory layer) ----------------------------------

def list_packs(ledger: Ledger) -> dict:
    return {"packs": ledger.list_packs()}


def save_pack(ledger: Ledger, *, pack_id=None, title: str, tags: list,
              content: str, enabled: bool = True, when_to_use: str = None) -> dict:
    """Create a pack (no id) or update an existing one (with id)."""
    title = (title or "").strip()
    if not title:
        raise ValueError("title required")
    if not (content or "").strip():
        raise ValueError("content required")
    if not isinstance(tags, list):
        raise ValueError("tags must be a list")
    when_to_use = (when_to_use or "").strip() or None
    if pack_id:
        ok = ledger.update_pack(int(pack_id), title=title, tags=tags,
                                content=content, enabled=enabled, when_to_use=when_to_use)
        if not ok:
            raise ValueError(f"pack {pack_id} not found")
        return {"id": int(pack_id), "updated": True, "pack": ledger.get_pack(int(pack_id))}
    new_id = ledger.create_pack(title, tags, content, enabled=enabled, when_to_use=when_to_use)
    return {"id": new_id, "created": True, "pack": ledger.get_pack(new_id)}


def delete_pack(ledger: Ledger, pack_id: int) -> dict:
    ok = ledger.delete_pack(int(pack_id))
    if not ok:
        raise ValueError(f"pack {pack_id} not found")
    return {"deleted": True, "id": int(pack_id)}


def recall(ledger: Ledger, message: str, limit: int = 8,
           log: bool = False, session_id: Optional[str] = None) -> dict:
    """Select which packs to inject for a user message. Used by pre_llm_call.

    The user message is resolved (LLM or keyword) against the vocabulary of all
    enabled packs' **titles and tags**; a pack is injected when its title or any
    of its tags is matched. When ``log`` is set and packs are injected, the
    result is recorded in recall_log for the UI."""
    from . import tagger
    packs = ledger.list_packs(enabled_only=True)
    if not packs:
        return {"tags": [], "method": "none", "count": 0, "context": "", "records": []}
    selected_ids, method = tagger.select_packs(message, [
        {"id": p["id"], "title": p["title"], "tags": p["tags"],
         "when_to_use": p.get("when_to_use") or ""}
        for p in packs])
    sel_set = set(selected_ids)
    hits = [p for p in packs if p["id"] in sel_set][:limit]
    if not hits:
        return {"tags": [], "method": method, "count": 0, "context": "", "records": [],
                "llm_configured": tagger.llm_configured()}
    titles = [p["title"] for p in hits]
    lines = ["（Hermes Loom 依情境帶入相關記憶 pack：" + "、".join(titles) + "）"]
    for p in hits:
        lines.append("【" + p["title"] + "】\n" + p["content"])
    context = "\n\n".join(lines)
    out_records = [{"id": "pack:" + str(p["id"]), "title": p["title"],
                    "value": (p["content"] if len(p["content"]) <= 300 else p["content"][:300] + "…"),
                    "tags": p["tags"]} for p in hits]
    if log:
        try:
            ledger.add_recall(message=message, method=method, tags=titles,
                              count=len(hits), records=out_records, session_id=session_id)
        except Exception:  # noqa: BLE001 - logging must never break a turn
            pass
    # `tags` carries the selected pack titles (what was injected) for the UI log.
    return {"tags": titles, "method": method, "count": len(hits), "context": context,
            "llm_configured": tagger.llm_configured(), "records": out_records}


# -- inspector mutations -----------------------------------------------------

def record_edit(ledger: Ledger, target_type: str, key: str, new_value: str, reason=None):
    if target_type in ("memory", "user"):
        return overrides.edit_memory_entry(ledger, target_type, key, new_value, reason=reason)
    if target_type == "skill":
        return overrides.edit_skill(ledger, key, new_value, reason=reason)
    if target_type == "hold":
        return overrides.edit_held(ledger, key, new_value, reason=reason)
    raise overrides.OverrideError(f"unknown target_type {target_type}")


# Category ⇄ store: category controls which file an entry lives in.
_CAT_TO_STORE = {"memory": "memory", "pref": "user"}


def record_recategorize(ledger: Ledger, target_type: str, key: str, to_cat: str, reason=None):
    """Recategorize a memory/user/hold entry. Category controls where it lives:
    記憶→MEMORY.md, 偏好→USER.md, 暫存(hold)→Loom-only (not compiled). Skills can't
    be recategorized. Returns the move result + the record's new id.
    """
    if target_type not in ("memory", "user", "hold"):
        raise overrides.OverrideError("只有記憶/偏好/暫存可以改分類（技能不適用）")
    if to_cat not in ("memory", "pref", "hold"):
        raise overrides.OverrideError(f"無法改成「{to_cat}」")

    if target_type == "hold":
        if to_cat == "hold":
            raise overrides.OverrideError("已經是暫存了")
        res = overrides.unhold_entry(ledger, key, _CAT_TO_STORE[to_cat], reason=reason)
    elif to_cat == "hold":
        res = overrides.hold_entry(ledger, target_type, key, reason=reason)
    else:
        res = overrides.move_memory_entry(ledger, target_type, key, _CAT_TO_STORE[to_cat], reason=reason)
    res["new_id"] = f"{res['to_target_type']}:{res['new_key']}"
    return res


def record_delete(ledger: Ledger, target_type: str, key: str, reason=None):
    if target_type in ("memory", "user"):
        return overrides.delete_memory_entry(ledger, target_type, key, reason=reason)
    if target_type == "skill":
        return overrides.delete_skill(ledger, key, hard=False, reason=reason)
    if target_type == "hold":
        return overrides.delete_held(ledger, key, reason=reason)
    raise overrides.OverrideError(f"unknown target_type {target_type}")
