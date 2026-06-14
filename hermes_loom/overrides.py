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

    try:
        target["text"] = new_text.strip()
        _atomic_write(path, serialize_entries(entries))
    except OSError as e:
        raise OverrideError(f"failed to write {path}: {e}") from e

    target_type = "user" if store_type == "user" else "memory"
    ledger.add_override(
        target_type=target_type, target_key=entry_key, override_type="edit",
        before_text=before, after_text=new_text.strip(), reason=reason, applied_by=applied_by,
    )
    event_id = ledger.add_event(
        kind="memory_replaced", target_type=target_type, action="manual_edit",
        target_key=entry_key, target_path=str(path),
        before_text=before, after_text=new_text.strip(),
        source_hint="manual_override", tool_name="loom",
        status="edited", metadata={"manual": True, "backup": str(backup), "reason": reason},
    )
    new_content = path.read_text(encoding="utf-8")
    ledger.add_memory_snapshot(store_type, new_content, _sha(new_content), source_event_id=event_id)
    return {"event_id": event_id, "before": before, "after": new_text.strip(), "backup": str(backup)}


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
