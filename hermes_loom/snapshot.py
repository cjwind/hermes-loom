"""Snapshots, bootstrap backfill, and the snapshot-diff fallback.

Why this exists: Hermes' plugin hooks may not cover every mutation point (and
some memory/skills predate Loom's install). So in addition to live hooks we:

  1. **Bootstrap** — on first run, snapshot current MEMORY.md/USER.md and all
     skills, recording them as ``*_snapshot_imported`` events (historical, not
     runtime-observed).
  2. **Reconcile (diff fallback)** — on later runs, compare current files to the
     last snapshot and synthesize add/replace/remove events for anything that
     changed without a hook. These are tagged ``source_hint='snapshot_diff'``
     and ``metadata.inferred=true`` so the UI can flag them as best-effort.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Optional

from . import config, hermes_state
from .ledger import Ledger
from .memory_parser import parse_entries

log = logging.getLogger("hermes_loom.snapshot")

_BOOTSTRAP_FLAG = "bootstrap_done"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ----- bootstrap -------------------------------------------------------------

def bootstrap(ledger: Ledger, force: bool = False) -> dict:
    """Import current memory + skills as historical snapshots. Idempotent."""
    if ledger.get_meta(_BOOTSTRAP_FLAG) and not force:
        return {"skipped": True, "reason": "already bootstrapped"}

    counts = {"memory": 0, "skills": 0}

    for store_type in ("memory", "user"):
        content = hermes_state.read_memory(store_type)
        if content is None:
            continue
        entries = parse_entries(content)
        event_id = ledger.add_event(
            kind="memory_snapshot_imported",
            target_type="user" if store_type == "user" else "memory",
            action="snapshot_import",
            target_path=str(
                config.user_md_path() if store_type == "user" else config.memory_md_path()
            ),
            after_text=content,
            source_hint="bootstrap",
            metadata={"historical": True, "entry_count": len(entries)},
        )
        ledger.add_memory_snapshot(store_type, content, _sha(content), source_event_id=event_id)
        counts["memory"] += 1

    for skill in hermes_state.list_skills():
        full = hermes_state.read_skill(skill["name"])
        if not full:
            continue
        event_id = ledger.add_event(
            kind="skill_snapshot_imported",
            target_type="skill",
            action="snapshot_import",
            target_key=skill["name"],
            target_path=skill["path"],
            after_text=full["content"],
            source_hint="bootstrap",
            metadata={"historical": True, "category": skill["category"]},
        )
        ledger.add_skill_snapshot(
            skill["name"], skill["path"], full["content"], skill["hash"],
            source_event_id=event_id,
        )
        counts["skills"] += 1

    ledger.set_meta(_BOOTSTRAP_FLAG, "1")
    return {"skipped": False, "imported": counts}


# ----- reconcile (diff fallback) --------------------------------------------

def reconcile_memory(ledger: Ledger, store_type: str) -> list[int]:
    """Diff current memory file vs last snapshot; emit inferred events.

    Returns the list of new event ids. Always re-snapshots if content changed.
    """
    new_event_ids: list[int] = []
    content = hermes_state.read_memory(store_type)
    if content is None:
        return new_event_ids
    cur_hash = _sha(content)
    last = ledger.latest_memory_snapshot(store_type)
    if last and last["snapshot_hash"] == cur_hash:
        return new_event_ids  # unchanged

    old_content = last["content"] if last else ""
    old_entries = {e["key"]: e for e in parse_entries(old_content)}
    new_entries = {e["key"]: e for e in parse_entries(content)}
    target_type = "user" if store_type == "user" else "memory"
    path = str(config.user_md_path() if store_type == "user" else config.memory_md_path())

    added = [k for k in new_entries if k not in old_entries]
    removed = [k for k in old_entries if k not in new_entries]

    # Heuristic: a single removed + single added likely == a replace.
    if len(added) == 1 and len(removed) == 1:
        eid = ledger.add_event(
            kind="memory_replaced", target_type=target_type, action="replace",
            target_key=added[0], target_path=path,
            before_text=old_entries[removed[0]]["text"],
            after_text=new_entries[added[0]]["text"],
            source_hint="snapshot_diff",
            metadata={"inferred": True, "prev_key": removed[0]},
        )
        new_event_ids.append(eid)
    else:
        for k in added:
            new_event_ids.append(ledger.add_event(
                kind="memory_added", target_type=target_type, action="add",
                target_key=k, target_path=path, after_text=new_entries[k]["text"],
                source_hint="snapshot_diff", metadata={"inferred": True},
            ))
        for k in removed:
            new_event_ids.append(ledger.add_event(
                kind="memory_removed", target_type=target_type, action="remove",
                target_key=k, target_path=path, before_text=old_entries[k]["text"],
                source_hint="snapshot_diff", metadata={"inferred": True},
            ))

    ledger.add_memory_snapshot(store_type, content, cur_hash)
    return new_event_ids


def reconcile_skills(ledger: Ledger) -> list[int]:
    """Diff current skills vs last snapshots; emit inferred create/edit/delete."""
    new_event_ids: list[int] = []
    current = {s["name"]: s for s in hermes_state.list_skills()}

    for name, skill in current.items():
        last = ledger.latest_skill_snapshot(name)
        if last and last["content_hash"] == skill["hash"]:
            continue
        full = hermes_state.read_skill(name)
        if not full:
            continue
        if last is None:
            eid = ledger.add_event(
                kind="skill_created", target_type="skill", action="create",
                target_key=name, target_path=skill["path"], after_text=full["content"],
                source_hint="snapshot_diff", metadata={"inferred": True, "category": skill["category"]},
            )
        else:
            eid = ledger.add_event(
                kind="skill_edited", target_type="skill", action="edit",
                target_key=name, target_path=skill["path"],
                before_text=last["content"], after_text=full["content"],
                source_hint="snapshot_diff", metadata={"inferred": True},
            )
        ledger.add_skill_snapshot(name, skill["path"], full["content"], skill["hash"], source_event_id=eid)
        new_event_ids.append(eid)

    # Deletions: snapshotted skills that no longer exist.
    known = {
        r["skill_name"]
        for r in ledger.conn.execute("SELECT DISTINCT skill_name FROM skill_snapshots").fetchall()
    }
    for name in known - set(current):
        # avoid re-emitting delete repeatedly
        recent = ledger.events_for_target("skill", name)
        if recent and recent[0]["kind"] == "skill_deleted":
            continue
        last = ledger.latest_skill_snapshot(name)
        new_event_ids.append(ledger.add_event(
            kind="skill_deleted", target_type="skill", action="delete",
            target_key=name, before_text=last["content"] if last else None,
            source_hint="snapshot_diff", metadata={"inferred": True},
        ))
    return new_event_ids


def reconcile_all(ledger: Ledger) -> dict:
    return {
        "memory": reconcile_memory(ledger, "memory"),
        "user": reconcile_memory(ledger, "user"),
        "skills": reconcile_skills(ledger),
    }


# ----- live snapshot sync ----------------------------------------------------
# A hook-observed write (plugin_hook) records an event but, on its own, leaves
# the stored snapshot stale. The next reconcile would then re-discover that same
# change as a `snapshot_diff` event whose newer timestamp overrides the precise
# plugin_hook provenance (`_origin_event` picks the most recent match). Advancing
# the snapshot right after a live write closes that gap: reconcile sees the hash
# already matches and emits nothing. Both are idempotent no-ops when up to date.

def capture_memory_snapshot(
    ledger: Ledger, store_type: str, source_event_id: Optional[int] = None
) -> Optional[int]:
    """Advance the memory snapshot to the file's current content. No-op if the
    latest snapshot already matches (or the file is absent). Returns the new
    snapshot id, or None."""
    content = hermes_state.read_memory(store_type)
    if content is None:
        return None
    cur_hash = _sha(content)
    last = ledger.latest_memory_snapshot(store_type)
    if last and last["snapshot_hash"] == cur_hash:
        return None
    return ledger.add_memory_snapshot(
        store_type, content, cur_hash, source_event_id=source_event_id
    )


def capture_skill_snapshot(
    ledger: Ledger, name: str, source_event_id: Optional[int] = None
) -> Optional[int]:
    """Advance a skill's snapshot to its current file content. No-op if already
    current or the skill no longer exists (e.g. a delete — the deletion is left
    for reconcile, which is guarded against re-emitting)."""
    full = hermes_state.read_skill(name)
    if not full:
        return None
    cur_hash = _sha(full["content"])
    last = ledger.latest_skill_snapshot(name)
    if last and last["content_hash"] == cur_hash:
        return None
    return ledger.add_skill_snapshot(
        name, full["path"], full["content"], cur_hash, source_event_id=source_event_id
    )
