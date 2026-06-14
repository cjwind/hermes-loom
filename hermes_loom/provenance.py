"""Provenance helpers — bind a growth event to *where it came from*.

When Hermes grows (a memory entry, a skill), we want to know which session and
which part of the conversation caused it. The plugin hook gives us a session id
in real time. To enrich it (and to backfill history) we read a best-effort
"message window" from the Hermes session store.

This is explicitly **best-effort**: precise message ids are not always available
at hook time, so we capture the surrounding user/assistant/tool messages as a
window and record a ``source_hint`` describing how confident we are.
"""

from __future__ import annotations

from typing import Optional

from . import hermes_state
from .ledger import Ledger


def capture_session_window(
    ledger: Ledger,
    session_id: Optional[str],
    *,
    window: int = 8,
    around_ts: Optional[float] = None,
) -> Optional[list]:
    """Cache session metadata and return a trimmed message window.

    If ``around_ts`` is given we center the window on that time (used by the
    state.db backfill, where we know exactly when the tool call happened).
    Otherwise we take the most recent messages (used by live hooks).
    """
    if not session_id:
        return None

    meta = hermes_state.get_session_meta(session_id)
    if meta:
        ledger.upsert_session(
            session_id=session_id,
            source=meta.get("source"),
            title=meta.get("title"),
            started_at=meta.get("started_at"),
            ended_at=meta.get("ended_at"),
            user_id=meta.get("user_id"),
        )

    if around_ts is not None:
        return _window_around(session_id, around_ts, window)

    ctx = hermes_state.get_session_context(session_id, limit=window)
    return ctx.get("messages") or None


def _window_around(session_id: str, ts: float, window: int) -> Optional[list]:
    conn = hermes_state._connect_ro()  # noqa: SLF001 - internal RO helper
    if not conn:
        return None
    try:
        half = max(1, window // 2)
        before = conn.execute(
            "SELECT role, tool_name, content, timestamp FROM messages "
            "WHERE session_id=? AND timestamp<=? ORDER BY timestamp DESC, id DESC LIMIT ?",
            (session_id, ts, half + 1),
        ).fetchall()
        after = conn.execute(
            "SELECT role, tool_name, content, timestamp FROM messages "
            "WHERE session_id=? AND timestamp>? ORDER BY timestamp ASC, id ASC LIMIT ?",
            (session_id, ts, half),
        ).fetchall()
        rows = list(reversed(before)) + list(after)
        out = []
        for r in rows:
            content = r["content"] or ""
            out.append({
                "role": r["role"],
                "tool_name": r["tool_name"],
                "timestamp": r["timestamp"],
                "snippet": content[:500],
                "truncated": len(content) > 500,
            })
        return out or None
    finally:
        conn.close()
