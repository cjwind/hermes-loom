"""Drift detection — is what's on disk still what Loom last snapshotted?

Read-only and stateless: nothing here writes to the ledger or to Hermes' files.
Per target (``USER.md`` / ``MEMORY.md`` / each ``SKILL.md``) we compare the live
file against Loom's *latest* snapshot and report:

  * **status** — an exact ``sha256`` compare, never a guess:
    ``in_sync`` / ``drifted`` / ``missing_file`` (snapshot exists, file gone) /
    ``untracked`` (on disk, never snapshotted) / ``no_baseline`` (neither).
  * **summary** — for memory/user, the §-separated entries are paired with
    ``difflib.SequenceMatcher`` so ``added`` / ``removed`` / ``changed`` are
    derived deterministically from its opcodes (NOT the key-set heuristic that
    ``snapshot.reconcile`` uses). Skills are line-level (``added`` / ``removed``).
  * **diff** (detail only) — a ``difflib.unified_diff`` of the full text.

"Drift" here means: changes Hermes made on disk that Loom hasn't absorbed yet.
Running ``reconcile``/``sync`` advances the snapshots and clears it.
"""

from __future__ import annotations

import difflib
import hashlib
from typing import Optional

from . import config, hermes_state
from .ledger import Ledger
from .memory_parser import parse_entries

# status values a target can take
IN_SYNC = "in_sync"
DRIFTED = "drifted"
MISSING_FILE = "missing_file"
UNTRACKED = "untracked"
NO_BASELINE = "no_baseline"

# statuses that do NOT count as pending drift
_CLEAN = (IN_SYNC, NO_BASELINE)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _entry_summary(old_text: Optional[str], new_text: Optional[str]) -> dict:
    """Entry-level add/remove/change counts via SequenceMatcher over §-entries.

    Deterministic: the opcodes define what's an insert/delete/replace, so an
    in-place edit reads as ``changed`` rather than the heuristic remove+add.
    """
    old = [e["text"] for e in parse_entries(old_text or "")]
    new = [e["text"] for e in parse_entries(new_text or "")]
    added = removed = changed = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=old, b=new, autojunk=False).get_opcodes():
        if tag == "replace":
            # an N→M replace region: pair up min(N,M) as edits, the rest is a
            # net add/remove — so 1→2 reads as "1 changed, 1 added".
            o, n = i2 - i1, j2 - j1
            common = min(o, n)
            changed += common
            added += n - common
            removed += o - common
        elif tag == "delete":
            removed += i2 - i1
        elif tag == "insert":
            added += j2 - j1
    return {"added": added, "removed": removed, "changed": changed}


def _line_summary(old_text: Optional[str], new_text: Optional[str]) -> dict:
    """Line-level add/remove counts (skills aren't §-entry structured)."""
    old = (old_text or "").splitlines()
    new = (new_text or "").splitlines()
    added = removed = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=old, b=new, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        removed += i2 - i1
        added += j2 - j1
    return {"added": added, "removed": removed}


def _unified(old_text: Optional[str], new_text: Optional[str]) -> list[str]:
    old = (old_text or "").splitlines()
    new = (new_text or "").splitlines()
    return list(difflib.unified_diff(
        old, new, fromfile="Loom snapshot", tofile="Hermes disk", lineterm=""))


# ----- per-target status -----------------------------------------------------

def _memory_target(ledger: Ledger, store_type: str) -> dict:
    name = "MEMORY.md" if store_type == "memory" else "USER.md"
    path = config.memory_md_path() if store_type == "memory" else config.user_md_path()
    live = hermes_state.read_memory(store_type)
    last = ledger.latest_memory_snapshot(store_type)
    t = {
        "id": store_type, "kind": "memory", "name": name, "path": str(path),
        "last_captured": last["captured_at"] if last else None,
    }
    if last is None and live is None:
        t["status"] = NO_BASELINE
    elif last is None:
        t["status"] = UNTRACKED
        t["summary"] = _entry_summary("", live)
    elif live is None:
        t["status"] = MISSING_FILE
    elif _sha(live) == last["snapshot_hash"]:
        t["status"] = IN_SYNC
    else:
        t["status"] = DRIFTED
        t["summary"] = _entry_summary(last["content"], live)
    return t


def _skill_targets(ledger: Ledger) -> list[dict]:
    live = {s["name"]: s for s in hermes_state.list_skills()}
    snapped = {
        r["skill_name"]
        for r in ledger.conn.execute("SELECT DISTINCT skill_name FROM skill_snapshots").fetchall()
    }
    items: list[dict] = []

    for name in sorted(live):
        s = live[name]
        last = ledger.latest_skill_snapshot(name)
        it = {
            "id": "skill:" + name, "kind": "skill", "name": name, "path": s["path"],
            "last_captured": last["captured_at"] if last else None,
        }
        if last is None:
            it["status"] = UNTRACKED
        elif s["hash"] == last["content_hash"]:
            it["status"] = IN_SYNC
        else:
            it["status"] = DRIFTED
            full = hermes_state.read_skill(name)
            it["summary"] = _line_summary(last["content"], full["content"] if full else "")
        items.append(it)

    # snapshotted skills with no live file = deleted on disk. A deletion that
    # reconcile already acknowledged (latest event is skill_deleted) is not
    # pending drift; one Loom hasn't absorbed yet is.
    for name in sorted(snapped - set(live)):
        evs = ledger.events_for_target("skill", name)
        if evs and evs[0]["kind"] == "skill_deleted":
            continue
        last = ledger.latest_skill_snapshot(name)
        items.append({
            "id": "skill:" + name, "kind": "skill", "name": name, "path": None,
            "status": MISSING_FILE,
            "last_captured": last["captured_at"] if last else None,
        })
    return items


def _count(items: list[dict]) -> dict:
    c = {"total": len(items), IN_SYNC: 0, DRIFTED: 0, MISSING_FILE: 0,
         UNTRACKED: 0, NO_BASELINE: 0}
    for it in items:
        c[it["status"]] = c.get(it["status"], 0) + 1
    return c


def summary(ledger: Ledger) -> dict:
    """Whole-install drift snapshot for the Status page (no full diffs)."""
    mem = _memory_target(ledger, "memory")
    usr = _memory_target(ledger, "user")
    skills = _skill_targets(ledger)

    skill_drift = sum(1 for it in skills if it["status"] not in _CLEAN)
    file_drift = sum(1 for t in (mem, usr) if t["status"] not in _CLEAN)
    drift_count = file_drift + skill_drift

    return {
        "overall": IN_SYNC if drift_count == 0 else DRIFTED,
        "drift_count": drift_count,
        "memory": mem,
        "user": usr,
        "skills": {
            "status": IN_SYNC if skill_drift == 0 else DRIFTED,
            "counts": _count(skills),
            "items": skills,
        },
    }


def detail(ledger: Ledger, target_id: str) -> Optional[dict]:
    """Full diff + summary for one target. Returns None for an unknown id."""
    if target_id in ("memory", "user"):
        name = "MEMORY.md" if target_id == "memory" else "USER.md"
        live = hermes_state.read_memory(target_id)
        last = ledger.latest_memory_snapshot(target_id)
        old = last["content"] if last else ""
        new = live if live is not None else ""
        return {
            "id": target_id, "name": name,
            "summary": _entry_summary(old, new),
            "diff": _unified(old, new),
        }
    if target_id.startswith("skill:"):
        nm = target_id[len("skill:"):]
        last = ledger.latest_skill_snapshot(nm)
        full = hermes_state.read_skill(nm)
        old = last["content"] if last else ""
        new = full["content"] if full else ""
        return {
            "id": target_id, "name": nm,
            "summary": _line_summary(old, new),
            "diff": _unified(old, new),
        }
    return None
