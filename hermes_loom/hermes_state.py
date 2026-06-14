"""Read-only access to Hermes **native** state.

This is the only module that reads ``~/.hermes`` for inspection purposes
(memory files, skills, the session store). Writes to native files live in
``overrides.py`` and are deliberately isolated. Nothing here mutates Hermes.

All DB access opens ``state.db`` read-only so Loom can never corrupt Hermes.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import List, Optional

from . import config, skill_origin


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ----- Memory files ----------------------------------------------------------

def read_memory(store_type: str) -> Optional[str]:
    """Return raw content of MEMORY.md or USER.md, or None if absent."""
    path = config.memory_md_path() if store_type == "memory" else config.user_md_path()
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def memory_hash(store_type: str) -> Optional[str]:
    content = read_memory(store_type)
    return _sha(content) if content is not None else None


# ----- Skills ----------------------------------------------------------------

def _parse_frontmatter(text: str) -> dict:
    """Minimal YAML-frontmatter reader (no PyYAML dependency).

    Handles the simple ``key: value`` and ``tags: [a, b]`` shapes used by
    Hermes SKILL.md files. Unknown/complex YAML is ignored gracefully.
    """
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    block = text[3:end].strip()
    data: dict = {}
    for line in block.splitlines():
        line = line.rstrip()
        if not line or line.lstrip().startswith("#") or ":" not in line:
            continue
        if line[0] in " \t":  # skip nested/multiline values for MVP
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if val.startswith("[") and val.endswith("]"):
            items = [v.strip().strip('"').strip("'") for v in val[1:-1].split(",")]
            data[key] = [v for v in items if v]
        else:
            data[key] = val
    return data


def list_skills() -> List[dict]:
    """Enumerate skills as ``{name, category, path, description, tags, mtime, hash}``.

    Skills live at ``skills/<category>/<skill>/SKILL.md``. We also tolerate a
    flat ``skills/<skill>/SKILL.md`` layout. Hidden/backup dirs are skipped.
    """
    root = config.skills_dir()
    out: List[dict] = []
    if not root.exists():
        return out
    for skill_md in sorted(root.glob("**/SKILL.md")):
        rel = skill_md.relative_to(root)
        parts = rel.parts
        if any(p.startswith(".") or p.endswith(".bak") for p in parts):
            continue
        try:
            content = skill_md.read_text(encoding="utf-8")
        except OSError:
            continue
        fm = _parse_frontmatter(content)
        skill_dir = skill_md.parent
        name = fm.get("name") or skill_dir.name
        category = parts[0] if len(parts) > 1 else ""
        origin = skill_origin.classify_skill_origin(fm)  # computed once, in the loader
        out.append({
            "name": name,
            "dir_name": skill_dir.name,
            "category": category,
            "path": str(skill_md),
            "rel_path": str(rel),
            "description": fm.get("description", ""),
            "tags": fm.get("tags", []),
            "mtime": skill_md.stat().st_mtime,
            "hash": _sha(content),
            "size": len(content),
            # origin classification (single source of truth: skill_origin.py)
            "is_agent_created": origin["is_agent_created"],
            "origin_type": origin["origin_type"],
            "author": origin["author"],
            "created_by": origin["created_by"],
        })
    return out


def find_skill(name: str) -> Optional[dict]:
    for s in list_skills():
        if s["name"] == name or s["dir_name"] == name:
            return s
    return None


def read_skill(name: str) -> Optional[dict]:
    s = find_skill(name)
    if not s:
        return None
    content = Path(s["path"]).read_text(encoding="utf-8")
    return {**s, "content": content}


# ----- Session store (state.db) ---------------------------------------------

def _connect_ro() -> Optional[sqlite3.Connection]:
    db = config.state_db_path()
    if not db.exists():
        return None
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def get_session_meta(session_id: str) -> Optional[dict]:
    conn = _connect_ro()
    if not conn:
        return None
    try:
        row = conn.execute(
            "SELECT id, source, user_id, title, started_at, ended_at, message_count, cwd "
            "FROM sessions WHERE id=?",
            (session_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


PLUGIN_NAME = "hermes-loom"


def _plugins_lists() -> dict:
    """Parse the ``plugins: {enabled: [...], disabled: [...]}`` block from
    config.yaml without a YAML dependency. Returns {'enabled': set, 'disabled': set}.
    """
    cfg = config.hermes_home() / "config.yaml"
    out = {"enabled": set(), "disabled": set()}
    if not cfg.exists():
        return out
    try:
        lines = cfg.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    in_plugins = False
    cur = None
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            in_plugins = line.startswith("plugins:")
            cur = None
            continue
        if not in_plugins:
            continue
        stripped = line.strip()
        if stripped in ("enabled:", "disabled:"):
            cur = stripped[:-1]
        elif stripped.startswith("- ") and cur:
            out[cur].add(stripped[2:].strip())
    return out


def plugin_status() -> dict:
    """Is the Loom plugin installed + enabled (per Hermes' own config)?"""
    installed = (config.skills_dir().parent / "plugins" / PLUGIN_NAME / "plugin.yaml").exists()
    lists = _plugins_lists()
    enabled = (PLUGIN_NAME in lists["enabled"]) and (PLUGIN_NAME not in lists["disabled"])
    return {"installed": installed, "enabled": enabled}


def gateway_status() -> dict:
    """Is the Hermes gateway (which performs auto-deposit) running?"""
    path = config.hermes_home() / "gateway_state.json"
    if not path.exists():
        return {"known": False, "running": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {"known": True, "running": data.get("gateway_state") == "running",
                "updated_at": data.get("updated_at")}
    except (OSError, json.JSONDecodeError):
        return {"known": False, "running": False}


def recent_sessions_with_prompt(limit: int = 40) -> List[dict]:
    """Recent sessions that carry an assembled ``system_prompt``, newest first.

    The system prompt is the fully-composed identity/context Hermes sent to the
    model (SOUL.md + memories + skills + tool framing + footer). We only list
    sessions that actually have one so the prompt viewer never shows blanks.
    """
    conn = _connect_ro()
    if not conn:
        return []
    try:
        rows = conn.execute(
            "SELECT id, title, source, model, provider, started_at, ended_at, "
            "       message_count, length(system_prompt) AS prompt_chars, "
            "       input_tokens, output_tokens "
            "FROM sessions "
            "WHERE system_prompt IS NOT NULL AND system_prompt != '' "
            "ORDER BY started_at DESC, rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        # Older Hermes schema without some columns — degrade to the essentials.
        rows = conn.execute(
            "SELECT id, title, source, model, started_at, message_count, "
            "       length(system_prompt) AS prompt_chars "
            "FROM sessions WHERE system_prompt IS NOT NULL AND system_prompt != '' "
            "ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_assembled_prompt(session_id: str) -> Optional[dict]:
    """Return the assembled ``system_prompt`` + metadata for one session."""
    conn = _connect_ro()
    if not conn:
        return None
    try:
        row = conn.execute(
            "SELECT id, title, source, model, started_at, ended_at, message_count, "
            "       system_prompt FROM sessions WHERE id=?",
            (session_id,),
        ).fetchone()
        if not row or not row["system_prompt"]:
            return None
        return dict(row)
    finally:
        conn.close()


def get_session_context(session_id: str, limit: int = 12) -> dict:
    """Best-effort simplified conversation context for a session.

    Returns recent user/assistant/tool messages (most recent ``limit``),
    trimmed for display. Used both by the UI's Session Context Viewer and by
    provenance window capture.
    """
    conn = _connect_ro()
    if not conn:
        return {"session_id": session_id, "available": False, "messages": []}
    try:
        meta = conn.execute(
            "SELECT id, source, title, started_at, ended_at FROM sessions WHERE id=?",
            (session_id,),
        ).fetchone()
        rows = conn.execute(
            "SELECT role, tool_name, content, timestamp FROM messages "
            "WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        msgs = []
        for r in reversed(rows):
            content = r["content"] or ""
            msgs.append({
                "role": r["role"],
                "tool_name": r["tool_name"],
                "timestamp": r["timestamp"],
                "snippet": content[:500],
                "truncated": len(content) > 500,
            })
        return {
            "session_id": session_id,
            "available": True,
            "meta": dict(meta) if meta else None,
            "messages": msgs,
        }
    finally:
        conn.close()
