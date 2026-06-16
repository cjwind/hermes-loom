"""Compile Hermes files from the Loom ledger.

Reconstructs ``MEMORY.md`` / ``USER.md`` / every ``SKILL.md`` from the full-content
snapshots Loom stores (``memory_snapshots`` / ``skill_snapshots``). This is the
reverse of snapshotting: Loom acts as a regenerable backup of Hermes' files.

Two outputs:
  * ``compile_to_dir``   — write into a fresh directory (default; never touches
    the live ``~/.hermes``).
  * ``compile_in_place`` — overwrite the real Hermes files, taking a timestamped
    backup of each first.

``as_of`` (epoch seconds) compiles a historical state: for each file we pick the
newest snapshot at or before that time. Without it, the latest snapshot is used.

Reliability note: snapshots are only as fresh as Loom's last observation/sync. Run
``hermes-loom sync`` first if you want the very latest live state captured.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Optional

from . import config
from .ledger import Ledger


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_as_of(s: Optional[str]) -> Optional[float]:
    """Parse an --as-of value (epoch, 'YYYY-MM-DD', or 'YYYY-MM-DD HH:MM[:SS]')."""
    if not s:
        return None
    s = s.strip()
    try:
        return float(s)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return time.mktime(time.strptime(s, fmt))
        except ValueError:
            continue
    raise ValueError(f"unrecognized --as-of value: {s!r}")


def _latest_memory(ledger: Ledger, store_type: str, as_of: Optional[float]):
    if as_of is None:
        return ledger.latest_memory_snapshot(store_type)
    row = ledger.conn.execute(
        "SELECT * FROM memory_snapshots WHERE store_type=? AND captured_at<=? "
        "ORDER BY captured_at DESC, id DESC LIMIT 1",
        (store_type, as_of),
    ).fetchone()
    return dict(row) if row else None


def _skill_names(ledger: Ledger) -> list[str]:
    return [r["skill_name"] for r in ledger.conn.execute(
        "SELECT DISTINCT skill_name FROM skill_snapshots").fetchall()]


def _latest_skill(ledger: Ledger, name: str, as_of: Optional[float]):
    if as_of is None:
        return ledger.latest_skill_snapshot(name)
    row = ledger.conn.execute(
        "SELECT * FROM skill_snapshots WHERE skill_name=? AND captured_at<=? "
        "ORDER BY captured_at DESC, id DESC LIMIT 1",
        (name, as_of),
    ).fetchone()
    return dict(row) if row else None


def _skill_rel_path(file_path: Optional[str], name: str) -> Path:
    """Recover the path of a SKILL.md relative to the skills root.

    Snapshots store the absolute file_path; we make it relative to the Hermes
    skills dir so the export mirrors the original layout. Falls back to
    ``<name>/SKILL.md`` when the path isn't under the skills root.
    """
    root = config.skills_dir()
    if file_path:
        p = Path(file_path)
        try:
            return p.relative_to(root)
        except ValueError:
            # different machine / path → keep the trailing <skill-dir>/SKILL.md
            if p.name == "SKILL.md":
                return Path(p.parent.name) / "SKILL.md"
    return Path(name) / "SKILL.md"


def collect(ledger: Ledger, as_of: Optional[float] = None) -> dict:
    """Gather the snapshot content to compile. Returns a manifest dict."""
    out = {"as_of": as_of, "memory": {}, "skills": [], "missing": []}
    for store_type, fname in (("memory", "MEMORY.md"), ("user", "USER.md")):
        snap = _latest_memory(ledger, store_type, as_of)
        if snap and snap.get("content") is not None:
            out["memory"][store_type] = {
                "filename": fname, "content": snap["content"],
                "captured_at": snap["captured_at"],
            }
        else:
            out["missing"].append(fname)
    for name in _skill_names(ledger):
        snap = _latest_skill(ledger, name, as_of)
        if snap and snap.get("content") is not None:
            out["skills"].append({
                "name": name, "content": snap["content"],
                "rel_path": str(_skill_rel_path(snap.get("file_path"), name)),
                "file_path": snap.get("file_path"),
                "captured_at": snap["captured_at"],
            })
        else:
            out["missing"].append(f"skill:{name}")
    return out


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".loomtmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _backup(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    backup_dir = config.file_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dest = backup_dir / f"{path.name}.compile-{stamp}.bak"
    dest.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return str(dest)


def compile_to_dir(ledger: Ledger, out_dir: Path, as_of: Optional[float] = None) -> dict:
    """Write reconstructed files into ``out_dir`` (never touches ~/.hermes)."""
    out_dir = Path(out_dir)
    data = collect(ledger, as_of)
    written = []
    for store in data["memory"].values():
        dest = out_dir / "memories" / store["filename"]
        _write(dest, store["content"])
        written.append(str(dest))
    for sk in data["skills"]:
        dest = out_dir / "skills" / sk["rel_path"]
        _write(dest, sk["content"])
        written.append(str(dest))
    return {"mode": "dir", "out_dir": str(out_dir), "written": written,
            "files": len(written), "missing": data["missing"], "as_of": as_of}


def compile_in_place(ledger: Ledger, as_of: Optional[float] = None) -> dict:
    """Overwrite the real Hermes files, backing up each first.

    Each target is written independently and records an append-only
    ``compile_event`` (status + fingerprint) so the drift panel knows what was
    last compiled. A write failure on one target is captured as ``compile_failed``
    and does not abort the others.
    """
    data = collect(ledger, as_of)
    written, backups, results, errors = [], [], [], []

    def _do(target: str, dest: Path, content: str) -> None:
        try:
            b = _backup(dest)
            if b:
                backups.append(b)
            _write(dest, content)
            fp = _sha(content)
            ledger.add_compile_event(target=target, status="compiled",
                                     fingerprint=fp, written_path=str(dest), mode="in_place")
            written.append(str(dest))
            results.append({"target": target, "status": "compiled",
                            "fingerprint": fp, "path": str(dest)})
        except OSError as e:
            ledger.add_compile_event(target=target, status="compile_failed",
                                     written_path=str(dest), mode="in_place", error=str(e))
            results.append({"target": target, "status": "compile_failed",
                            "error": str(e), "path": str(dest)})
            errors.append({"target": target, "error": str(e)})

    for store_type, store in data["memory"].items():
        target = "user" if store_type == "user" else "memory"
        dest = config.memory_md_path() if store_type == "memory" else config.user_md_path()
        _do(target, dest, store["content"])
    for sk in data["skills"]:
        # use the recorded absolute path when valid for this machine, else the
        # path under the live skills dir reconstructed from rel_path
        dest = Path(sk["file_path"]) if sk.get("file_path") else (config.skills_dir() / sk["rel_path"])
        if not str(dest).startswith(str(config.skills_dir())):
            dest = config.skills_dir() / sk["rel_path"]
        _do("skill:" + sk["name"], dest, sk["content"])

    return {"mode": "in_place", "written": written, "files": len(written),
            "backups": backups, "missing": data["missing"], "as_of": as_of,
            "results": results, "errors": errors}
