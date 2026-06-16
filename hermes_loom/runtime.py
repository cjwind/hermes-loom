"""Runtime targets: compile + drift status — Loom as Hermes' control plane.

This is the read model behind the Compile / Drift Status panel. It answers, per
runtime target (``SOUL.md`` / ``USER.md`` / ``MEMORY.md`` / managed skills):

  * **compile_status** — has Loom ever compiled this out? (never_compiled / compiled
    / compile_failed)
  * **drift_status** — does the file on disk still match what Loom last compiled?
    (in_sync / drifted / unknown)
  * managed / unmanaged / divergent item counts (best-effort, see below)
  * the last-compiled and current-runtime fingerprints

Drift is fingerprint-based and does NOT assume Loom is the only writer: it compares
the fingerprint Loom recorded at its last successful compile (``compile_events``)
against the file's current content. Any external write by Hermes shows up as drift.

Managed vs unmanaged is best-effort and reuses existing snapshots — there is no
separate bookkeeping system:

  * **managed**   = items present in what Loom last compiled out (recovered from the
    memory/skill snapshot that was current at compile time) and still in the file.
  * **unmanaged** = items in the runtime file that Loom never compiled (Hermes wrote
    them after / independently of Loom).
  * **divergent** = items Loom compiled that are no longer in the file as compiled
    (edited or removed externally).

These counts are NOT a guaranteed block-level diff — for memory/user they are entry
(content-hash) level, and an edited entry shows as one divergent + one unmanaged.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Optional

from . import compiler, config, hermes_state, soul
from .ledger import Ledger
from .memory_parser import parse_entries

# The runtime targets surfaced by the panel. "skills" is an aggregate over every
# managed skill; the rest are single files.
TARGETS = ("soul", "user", "memory", "skills")

# memory snapshots are keyed by store_type ('memory' | 'user'); the SOUL target has
# no entry/§ structure, so it is treated whole-file.
_STORE_FOR_TARGET = {"memory": "memory", "user": "user"}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ----- runtime file reads (best-effort, never raise) -------------------------

def _file_for(target: str) -> Optional[Path]:
    if target == "soul":
        return config.soul_md_path()
    if target == "user":
        return config.user_md_path()
    if target == "memory":
        return config.memory_md_path()
    return None


def _runtime_content(target: str):
    """(content, fingerprint) of the current runtime file, or (None, None)."""
    p = _file_for(target)
    if p is None or not p.exists():
        return None, None
    try:
        c = p.read_text(encoding="utf-8")
    except OSError:
        return None, None
    return c, _sha(c)


def _mtime(p: Optional[Path]) -> Optional[float]:
    try:
        return p.stat().st_mtime if p else None
    except OSError:
        return None


def _entry_keys(content: Optional[str]) -> set:
    return {e["key"] for e in parse_entries(content or "")}


# ----- per-target status -----------------------------------------------------

def _file_target_status(ledger: Ledger, target: str) -> dict:
    latest = ledger.latest_compile_event(target)
    success = ledger.latest_successful_compile(target)

    if latest is None:
        compile_status = "never_compiled"
    elif latest["status"] == "compiled":
        compile_status = "compiled"
    else:
        compile_status = "compile_failed"

    baseline_fp = success["fingerprint"] if success else None
    last_compiled_at = success["timestamp"] if success else (
        latest["timestamp"] if latest else None)
    content, current_fp = _runtime_content(target)

    if baseline_fp is None:
        drift = "unknown"
    elif current_fp is None:
        drift = "drifted"               # compiled before, file now missing
    elif current_fp == baseline_fp:
        drift = "in_sync"
    else:
        drift = "drifted"

    managed = unmanaged = divergent = 0
    if target == "soul":
        # SOUL is whole-file and fully Loom-owned by design.
        if compile_status == "never_compiled":
            unmanaged = 1 if content is not None else 0
        else:
            managed = 1
            divergent = 1 if drift == "drifted" else 0
    else:
        store = _STORE_FOR_TARGET[target]
        runtime_keys = _entry_keys(content)
        compiled_content = None
        if success:
            snap = compiler._latest_memory(ledger, store, success["timestamp"])  # noqa: SLF001
            if snap and snap.get("content") is not None:
                compiled_content = snap["content"]
        compiled_keys = _entry_keys(compiled_content) if compiled_content is not None else set()
        managed = len(compiled_keys & runtime_keys)
        unmanaged = len(runtime_keys - compiled_keys)
        divergent = len(compiled_keys - runtime_keys)

    return {
        "target_name": target,
        "kind": "file",
        "compile_status": compile_status,
        "drift_status": drift,
        "last_compiled_at": last_compiled_at,
        "last_runtime_observed_at": _mtime(_file_for(target)),
        "managed_item_count": managed,
        "unmanaged_item_count": unmanaged,
        "divergent_item_count": divergent,
        "last_compiled_fingerprint": baseline_fp,
        "current_runtime_fingerprint": current_fp,
        "last_error": latest["error"] if (latest and latest["status"] == "compile_failed") else None,
    }


def _skills_status(ledger: Ledger) -> dict:
    skill_targets = ledger.compiled_skill_targets()      # ['skill:foo', ...]
    runtime = {s["name"]: s for s in hermes_state.list_skills()}

    managed = divergent = 0
    compiled_pairs, current_pairs = [], []
    last_compiled_at = None
    most_recent = None                                    # latest event across skills

    for t in skill_targets:
        latest = ledger.latest_compile_event(t)
        if latest and (most_recent is None or latest["timestamp"] > most_recent["timestamp"]):
            most_recent = latest
        succ = ledger.latest_successful_compile(t)
        if not succ:
            continue
        name = t.split("skill:", 1)[1]
        managed += 1
        if succ["timestamp"] and (last_compiled_at is None or succ["timestamp"] > last_compiled_at):
            last_compiled_at = succ["timestamp"]
        cur = runtime.get(name)
        cur_fp = cur["hash"] if cur else None
        compiled_pairs.append((name, succ["fingerprint"]))
        current_pairs.append((name, cur_fp))
        if cur_fp != succ["fingerprint"]:
            divergent += 1

    unmanaged = len([n for n in runtime if ("skill:" + n) not in skill_targets])

    if most_recent is None:
        compile_status = "never_compiled"
    elif most_recent["status"] == "compiled":
        compile_status = "compiled"
    else:
        compile_status = "compile_failed"

    if managed == 0:
        drift = "unknown"
    elif divergent > 0:
        drift = "drifted"
    else:
        drift = "in_sync"

    def _agg(pairs):
        if not pairs:
            return None
        return _sha("\n".join(f"{n}:{fp or ''}" for n, fp in sorted(pairs)))

    last_observed = None
    for n in runtime:
        m = _mtime(Path(runtime[n]["path"]))
        if m and (last_observed is None or m > last_observed):
            last_observed = m

    return {
        "target_name": "skills",
        "kind": "skills",
        "compile_status": compile_status,
        "drift_status": drift,
        "last_compiled_at": last_compiled_at,
        "last_runtime_observed_at": last_observed,
        "managed_item_count": managed,
        "unmanaged_item_count": unmanaged,
        "divergent_item_count": divergent,
        "last_compiled_fingerprint": _agg(compiled_pairs),
        "current_runtime_fingerprint": _agg(current_pairs),
        "last_error": most_recent["error"] if (most_recent and most_recent["status"] == "compile_failed") else None,
    }


def _target_status(ledger: Ledger, target: str) -> dict:
    return _skills_status(ledger) if target == "skills" else _file_target_status(ledger, target)


def runtime_status(ledger: Ledger) -> dict:
    """Summary of every runtime target's compile + drift state."""
    targets = [_target_status(ledger, t) for t in TARGETS]
    summary = {
        "targets": len(targets),
        "in_sync": sum(1 for t in targets if t["drift_status"] == "in_sync"),
        "drifted": sum(1 for t in targets if t["drift_status"] == "drifted"),
        "unknown": sum(1 for t in targets if t["drift_status"] == "unknown"),
        "never_compiled": sum(1 for t in targets if t["compile_status"] == "never_compiled"),
        "compile_failed": sum(1 for t in targets if t["compile_status"] == "compile_failed"),
        "managed_total": sum(t["managed_item_count"] for t in targets),
        "unmanaged_total": sum(t["unmanaged_item_count"] for t in targets),
        "divergent_total": sum(t["divergent_item_count"] for t in targets),
    }
    # "Is Loom in control?" — at least one target compiled and nothing drifted.
    summary["in_control"] = (summary["drifted"] == 0
                             and summary["never_compiled"] < len(targets))
    return {"targets": targets, "summary": summary, "generated_at": time.time()}


# ----- per-target detail -----------------------------------------------------

def _diff_summary(ledger: Ledger, target: str, status: dict) -> dict:
    """Best-effort, lightweight diff: which items are unmanaged / divergent."""
    out = {"unmanaged": [], "divergent": [], "note": None}
    if target == "soul":
        if status["drift_status"] == "drifted":
            out["note"] = "soul_drifted"
        return out
    if target == "skills":
        runtime = {s["name"]: s for s in hermes_state.list_skills()}
        for t in ledger.compiled_skill_targets():
            name = t.split("skill:", 1)[1]
            succ = ledger.latest_successful_compile(t)
            if not succ:
                continue
            cur = runtime.get(name)
            if cur is None or cur["hash"] != succ["fingerprint"]:
                out["divergent"].append(name)
        out["unmanaged"] = [n for n in runtime if ("skill:" + n) not in ledger.compiled_skill_targets()]
        return out
    # memory / user: entry-level
    store = _STORE_FOR_TARGET[target]
    content, _ = _runtime_content(target)
    runtime_entries = {e["key"]: e["text"] for e in parse_entries(content or "")}
    success = ledger.latest_successful_compile(target)
    compiled_entries: dict = {}
    if success:
        snap = compiler._latest_memory(ledger, store, success["timestamp"])  # noqa: SLF001
        if snap and snap.get("content") is not None:
            compiled_entries = {e["key"]: e["text"] for e in parse_entries(snap["content"])}
    unmanaged_keys = [k for k in runtime_entries if k not in compiled_entries]
    divergent_keys = [k for k in compiled_entries if k not in runtime_entries]

    def _clip(s: str) -> str:
        s = (s or "").strip().replace("\n", " ")
        return s[:80] + ("…" if len(s) > 80 else "")

    out["unmanaged"] = [_clip(runtime_entries[k]) for k in unmanaged_keys[:8]]
    out["divergent"] = [_clip(compiled_entries[k]) for k in divergent_keys[:8]]
    out["unmanaged_total"] = len(unmanaged_keys)
    out["divergent_total"] = len(divergent_keys)
    return out


def _recent_events(ledger: Ledger, target: str) -> dict:
    """Recent compile events + related growth events for the target."""
    if target == "skills":
        compiles = ledger.recent_compile_events(like="skill:%", limit=15)
        growth = ledger.query_events(target_type="skill", limit=10)
    elif target == "soul":
        compiles = ledger.recent_compile_events(target="soul", limit=15)
        growth = []                     # SOUL isn't tracked in growth_events
    else:
        compiles = ledger.recent_compile_events(target=target, limit=15)
        growth = ledger.query_events(target_type=target, limit=10)
    return {
        "compiles": compiles,
        "growth": [
            {"id": g["id"], "kind": g["kind"], "action": g.get("action"),
             "source_hint": g.get("source_hint"), "timestamp": g["timestamp"],
             "target_key": g.get("target_key")}
            for g in growth
        ],
    }


def target_detail(ledger: Ledger, target: str) -> Optional[dict]:
    if target not in TARGETS:
        return None
    status = _target_status(ledger, target)
    status["diff"] = _diff_summary(ledger, target, status)
    status["events"] = _recent_events(ledger, target)
    return status


# ----- compile orchestration -------------------------------------------------

def compile_all(ledger: Ledger, *, include_soul: bool = True) -> dict:
    """Compile every target out to the Hermes runtime files.

    SOUL compiles from its DB version; memory/user/skills compile from snapshots
    (via ``compiler.compile_in_place``). Each target records its own compile_event.
    Returns a structured, per-target result.
    """
    results, errors, written = [], [], []

    if include_soul and ledger.latest_soul_version():
        try:
            r = soul.compile_to_hermes(ledger)        # records its own compile_event
            written.append(r["path"])
            results.append({"target": "soul", "status": "compiled",
                            "fingerprint": r.get("fingerprint"), "path": r["path"]})
        except Exception as e:                         # noqa: BLE001 - report, don't crash
            ledger.add_compile_event(target="soul", status="compile_failed",
                                     written_path=str(config.soul_md_path()), error=str(e))
            results.append({"target": "soul", "status": "compile_failed", "error": str(e)})
            errors.append({"target": "soul", "error": str(e)})

    mem = compiler.compile_in_place(ledger)
    results.extend(mem["results"])
    errors.extend(mem["errors"])
    written.extend(mem["written"])

    return {
        "ok": not errors,
        "results": results,
        "written": written,
        "backups": mem.get("backups", []),
        "missing": mem.get("missing", []),
        "errors": errors,
        "compiled": sum(1 for r in results if r["status"] == "compiled"),
        "failed": len(errors),
    }
