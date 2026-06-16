"""SOUL.md management — Loom owns an editable copy, compiles it out to Hermes.

Unlike memory/skills (which Loom *observes* growing inside Hermes), SOUL.md is
authored here: the UI edits it, every save lands as an append-only version in the
Loom DB, and a separate compile step writes the current DB content out to
``~/.hermes/SOUL.md`` (taking a timestamped backup first).

SOUL.md is a plain free-form identity file — Hermes reads it verbatim
(``prompt_builder.load_soul_md``: ``read_text().strip()``), with no entry/§
parsing or round-trip drift gate. So we store and write the content byte-for-byte
and never re-serialize it (the bug that jammed USER.md cannot happen here).
"""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import Optional

from . import config
from .ledger import Ledger

log = logging.getLogger("hermes_loom.soul")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_disk() -> Optional[str]:
    path = config.soul_md_path()
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _seed_from_disk(ledger: Ledger) -> Optional[dict]:
    """If the DB has no SOUL version yet, import the live file as the first one."""
    if ledger.latest_soul_version():
        return None
    disk = _read_disk()
    if disk is None:
        return None
    ledger.add_soul_version(disk, _sha(disk), source="seed",
                            note="從 ~/.hermes/SOUL.md 匯入")
    return ledger.latest_soul_version()


def current(ledger: Ledger) -> dict:
    """Current SOUL state: the latest DB version plus live-file sync status."""
    _seed_from_disk(ledger)
    latest = ledger.latest_soul_version()
    disk = _read_disk()
    disk_hash = _sha(disk) if disk is not None else None
    db_hash = latest["content_hash"] if latest else None
    return {
        "content": latest["content"] if latest else (disk or ""),
        "in_db": latest is not None,
        "version_id": latest["id"] if latest else None,
        "source": latest["source"] if latest else None,
        "note": latest["note"] if latest else None,
        "updated_at": latest["created_at"] if latest else None,
        "disk": {
            "exists": disk is not None,
            "path": str(config.soul_md_path()),
            "hash": disk_hash,
        },
        # True when the live file already matches the current DB content (nothing
        # to compile). None when there is no DB version yet.
        "in_sync": (db_hash == disk_hash) if latest else None,
        "history": ledger.soul_history(limit=20),
    }


def save(ledger: Ledger, content: str, *, note: Optional[str] = None) -> dict:
    """Persist edited SOUL content as a new DB version (no file write).

    Idempotent: saving content identical to the current version is a no-op.
    """
    if content is None:
        raise ValueError("content required")
    h = _sha(content)
    latest = ledger.latest_soul_version()
    if latest and latest["content_hash"] == h:
        return {"saved": False, "unchanged": True, "version_id": latest["id"]}
    vid = ledger.add_soul_version(content, h, source="ui_edit", note=note)
    return {"saved": True, "unchanged": False, "version_id": vid, "hash": h}


def _backup_disk() -> Optional[str]:
    path = config.soul_md_path()
    if not path.exists():
        return None
    backup_dir = config.file_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dest = backup_dir / f"SOUL.md.compile-{stamp}.bak"
    dest.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return str(dest)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".loomtmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def compile_to_hermes(ledger: Ledger) -> dict:
    """Write the current DB SOUL content out to ``~/.hermes/SOUL.md``.

    Backs up any existing file first. Raises if there is no DB version to compile.
    """
    latest = ledger.latest_soul_version()
    if not latest:
        raise ValueError("no SOUL content in Loom yet — save one first")
    path = config.soul_md_path()
    backup = _backup_disk()
    fp = _sha(latest["content"])
    _atomic_write(path, latest["content"])
    # record the compile so the drift panel has a baseline fingerprint for SOUL
    ledger.add_compile_event(target="soul", status="compiled",
                             fingerprint=fp, written_path=str(path), mode="in_place")
    return {
        "compiled": True,
        "path": str(path),
        "backup": backup,
        "bytes": len(latest["content"].encode("utf-8")),
        "fingerprint": fp,
        "version_id": latest["id"],
    }
