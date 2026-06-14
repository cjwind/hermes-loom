"""Manual tuning — apply human edits to the **real** Hermes files, safely.

Critical requirement: an override must change the underlying data source Hermes
actually uses (MEMORY.md / USER.md / a skill's SKILL.md), not just the ledger.

Safety rules:
  * Snapshot the whole file into the ledger *before* touching it.
  * Also drop a timestamped file backup under ``LOOM_HOME/backups``.
  * Patch at entry granularity for memory (never blindly rewrite unrelated text).
  * On any failure, raise a clear error and leave the file untouched.
  * Record both a ``manual_overrides`` row and a ``growth_events`` row, each
    carrying before/after.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Optional

from . import config, hermes_state
from .ledger import Ledger
from .memory_parser import parse_entries, serialize_entries


class OverrideError(Exception):
    pass


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _backup_file(path: Path) -> Path:
    backup_dir = config.file_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dest = backup_dir / f"{path.name}.{stamp}.bak"
    dest.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return dest


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".loomtmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


# ----- memory overrides ------------------------------------------------------

def _memory_path(store_type: str) -> Path:
    return config.memory_md_path() if store_type == "memory" else config.user_md_path()


def edit_memory_entry(
    ledger: Ledger, store_type: str, entry_key: str, new_text: str,
    *, reason: Optional[str] = None, applied_by: str = "loom-ui",
) -> dict:
    """Replace a single memory entry (addressed by stable key) with new text."""
    path = _memory_path(store_type)
    if not path.exists():
        raise OverrideError(f"{store_type} file does not exist: {path}")
    content = path.read_text(encoding="utf-8")
    entries = parse_entries(content)
    target = next((e for e in entries if e["key"] == entry_key), None)
    if target is None:
        raise OverrideError(f"entry {entry_key} not found in {store_type}")

    before = target["text"]
    if not new_text.strip():
        raise OverrideError("new text is empty; use delete instead")

    # snapshot before mutation
    ledger.add_memory_snapshot(store_type, content, _sha(content))
    backup = _backup_file(path)

    new_text = new_text.strip()
    try:
        target["text"] = new_text
        _atomic_write(path, serialize_entries(entries))
    except OSError as e:
        raise OverrideError(f"failed to write {path}: {e}") from e

    # Key the override/event by the NEW content's key so the rebuilt record
    # (addressed by current content hash) can find its own edit history.
    from .memory_parser import entry_key as _ekey
    new_key = _ekey(new_text)
    target_type = "user" if store_type == "user" else "memory"
    ledger.add_override(
        target_type=target_type, target_key=new_key, override_type="edit",
        before_text=before, after_text=new_text, reason=reason, applied_by=applied_by,
    )
    event_id = ledger.add_event(
        kind="memory_replaced", target_type=target_type, action="manual_edit",
        target_key=new_key, target_path=str(path),
        before_text=before, after_text=new_text,
        source_hint="manual_override", tool_name="loom",
        status="edited", metadata={"manual": True, "backup": str(backup),
                                   "reason": reason, "prev_key": entry_key},
    )
    new_content = path.read_text(encoding="utf-8")
    ledger.add_memory_snapshot(store_type, new_content, _sha(new_content), source_event_id=event_id)
    return {"event_id": event_id, "key": new_key, "before": before,
            "after": new_text, "backup": str(backup)}


def add_memory_entry(
    ledger: Ledger, store_type: str, text: str,
    *, reason: Optional[str] = None, applied_by: str = "loom-ui",
) -> dict:
    """Append a new entry (used to undo a delete). Creates the file if absent."""
    text = (text or "").strip()
    if not text:
        raise OverrideError("entry text is empty")
    path = _memory_path(store_type)
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    if content:
        ledger.add_memory_snapshot(store_type, content, _sha(content))
        backup = str(_backup_file(path))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        backup = None
    entries = parse_entries(content)
    from .memory_parser import entry_key
    new_key = entry_key(text)
    if any(e["key"] == new_key for e in entries):
        raise OverrideError("an identical entry already exists")
    entries.append({"key": new_key, "text": text})
    try:
        _atomic_write(path, serialize_entries(entries))
    except OSError as e:
        raise OverrideError(f"failed to write {path}: {e}") from e

    target_type = "user" if store_type == "user" else "memory"
    ledger.add_override(target_type=target_type, target_key=new_key, override_type="edit",
                        before_text=None, after_text=text, reason=reason, applied_by=applied_by)
    event_id = ledger.add_event(
        kind="memory_added", target_type=target_type, action="manual_add",
        target_key=new_key, target_path=str(path), after_text=text,
        source_hint="manual_override", tool_name="loom", status="edited",
        metadata={"manual": True, "backup": backup, "reason": reason})
    new_content = path.read_text(encoding="utf-8")
    ledger.add_memory_snapshot(store_type, new_content, _sha(new_content), source_event_id=event_id)
    return {"event_id": event_id, "key": new_key, "after": text, "backup": backup}


def delete_memory_entry(
    ledger: Ledger, store_type: str, entry_key: str,
    *, reason: Optional[str] = None, applied_by: str = "loom-ui",
) -> dict:
    path = _memory_path(store_type)
    if not path.exists():
        raise OverrideError(f"{store_type} file does not exist: {path}")
    content = path.read_text(encoding="utf-8")
    entries = parse_entries(content)
    target = next((e for e in entries if e["key"] == entry_key), None)
    if target is None:
        raise OverrideError(f"entry {entry_key} not found in {store_type}")
    before = target["text"]

    ledger.add_memory_snapshot(store_type, content, _sha(content))
    backup = _backup_file(path)

    remaining = [e for e in entries if e["key"] != entry_key]
    try:
        _atomic_write(path, serialize_entries(remaining))
    except OSError as e:
        raise OverrideError(f"failed to write {path}: {e}") from e

    target_type = "user" if store_type == "user" else "memory"
    ledger.add_override(
        target_type=target_type, target_key=entry_key, override_type="delete",
        before_text=before, after_text=None, reason=reason, applied_by=applied_by,
    )
    event_id = ledger.add_event(
        kind="memory_removed", target_type=target_type, action="manual_delete",
        target_key=entry_key, target_path=str(path), before_text=before, after_text=None,
        source_hint="manual_override", tool_name="loom",
        status="edited", metadata={"manual": True, "backup": str(backup), "reason": reason},
    )
    new_content = path.read_text(encoding="utf-8")
    ledger.add_memory_snapshot(store_type, new_content, _sha(new_content), source_event_id=event_id)
    return {"event_id": event_id, "before": before, "backup": str(backup)}


# ----- skill overrides -------------------------------------------------------

def edit_skill(
    ledger: Ledger, skill_name: str, new_content: str,
    *, reason: Optional[str] = None, applied_by: str = "loom-ui",
) -> dict:
    """Rewrite a skill's SKILL.md. We snapshot before and back up the file."""
    skill = hermes_state.find_skill(skill_name)
    if not skill:
        raise OverrideError(f"skill not found: {skill_name}")
    path = Path(skill["path"])
    before = path.read_text(encoding="utf-8")
    if not new_content.strip():
        raise OverrideError("new skill content is empty; use delete instead")

    ledger.add_skill_snapshot(skill_name, str(path), before, _sha(before))
    backup = _backup_file(path)

    try:
        _atomic_write(path, new_content)
    except OSError as e:
        raise OverrideError(f"failed to write {path}: {e}") from e

    ledger.add_override(
        target_type="skill", target_key=skill_name, override_type="edit",
        before_text=before, after_text=new_content, reason=reason, applied_by=applied_by,
    )
    event_id = ledger.add_event(
        kind="skill_edited", target_type="skill", action="manual_edit",
        target_key=skill_name, target_path=str(path),
        before_text=before, after_text=new_content,
        source_hint="manual_override", tool_name="loom",
        status="edited", metadata={"manual": True, "backup": str(backup), "reason": reason},
    )
    ledger.add_skill_snapshot(skill_name, str(path), new_content, _sha(new_content), source_event_id=event_id)
    return {"event_id": event_id, "backup": str(backup)}


def annotate_record(ledger: Ledger, target_type: str, target_key: str,
                    text: str, *, applied_by: str = "loom-ui") -> dict:
    """Attach (or clear, if empty) a private note to a record.

    Annotations are Loom-side only — they never touch Hermes' files (per design:
    "不會改動沉澱內容"). Recorded in record_state + manual_overrides.
    """
    prev = (ledger.get_record_state(target_type, target_key) or {}).get("annotation")
    text = (text or "").strip()
    ledger.upsert_record_state(target_type, target_key,
                               annotation=text or None, annotation_at=time.time())
    ledger.add_override(target_type=target_type, target_key=target_key,
                        override_type="annotate", before_text=prev,
                        after_text=text or None, reason=None, applied_by=applied_by)
    return {"annotation": text or None}


def reclassify_record(ledger: Ledger, target_type: str, target_key: str,
                      to_cat: str, *, from_cat: str | None = None,
                      applied_by: str = "loom-ui") -> dict:
    """Move a record to a different Loom category.

    Categories are a Loom-side organizational layer (Hermes itself has no
    categories), so this updates record_state only, plus an override row.
    """
    ledger.upsert_record_state(target_type, target_key,
                               cat=to_cat, reclass_from=from_cat,
                               reclass_to=to_cat, reclass_at=time.time())
    ledger.add_override(target_type=target_type, target_key=target_key,
                        override_type="reclassify", before_text=from_cat,
                        after_text=to_cat, reason=None, applied_by=applied_by)
    return {"cat": to_cat, "from": from_cat}


def set_pin(ledger: Ledger, target_type: str, target_key: str, pinned: bool) -> dict:
    """Toggle a pin (immediate, no history — matches the design)."""
    ledger.upsert_record_state(target_type, target_key, pinned=1 if pinned else 0)
    return {"pinned": bool(pinned)}


def delete_skill(
    ledger: Ledger, skill_name: str, *, hard: bool = False,
    reason: Optional[str] = None, applied_by: str = "loom-ui",
) -> dict:
    """Disable a skill. Default is a *soft* disable: rename SKILL.md -> SKILL.md.disabled
    (so Hermes stops loading it but nothing is lost). ``hard=True`` removes the file
    (a backup is always kept in the ledger + backups dir)."""
    skill = hermes_state.find_skill(skill_name)
    if not skill:
        raise OverrideError(f"skill not found: {skill_name}")
    path = Path(skill["path"])
    before = path.read_text(encoding="utf-8")

    ledger.add_skill_snapshot(skill_name, str(path), before, _sha(before))
    backup = _backup_file(path)

    try:
        if hard:
            path.unlink()
            new_path = None
        else:
            new_path = path.with_name(path.name + ".disabled")
            path.rename(new_path)
    except OSError as e:
        raise OverrideError(f"failed to disable {path}: {e}") from e

    ledger.add_override(
        target_type="skill", target_key=skill_name, override_type="delete",
        before_text=before, after_text=None, reason=reason, applied_by=applied_by,
    )
    event_id = ledger.add_event(
        kind="skill_deleted", target_type="skill",
        action="manual_hard_delete" if hard else "manual_disable",
        target_key=skill_name, target_path=str(path), before_text=before, after_text=None,
        source_hint="manual_override", tool_name="loom",
        status="edited",
        metadata={"manual": True, "hard": hard, "backup": str(backup),
                  "disabled_path": str(new_path) if not hard else None, "reason": reason},
    )
    return {"event_id": event_id, "backup": str(backup), "hard": hard}
