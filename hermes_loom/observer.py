"""The observer core — turns "Hermes changed something" into ledger events.

Deliberately decoupled from the Hermes runtime so it is fully unit-testable
without a live Hermes. Three callers drive it:

  * ``plugin.py``      — live hooks (best provenance, real-time)
  * ``ingest.py``      — backfill from state.db tool calls (precise, offline)
  * ``snapshot.py``    — snapshot-diff fallback + bootstrap (coarse)

Every public method is wrapped so a failure here can never propagate into the
caller (the plugin must never crash Hermes' main flow).
"""

from __future__ import annotations

import logging
from typing import Optional

from . import provenance
from .ledger import Ledger

log = logging.getLogger("hermes_loom.observer")

_MEMORY_ACTION_KIND = {
    "add": "memory_added",
    "added": "memory_added",
    "append": "memory_added",
    "replace": "memory_replaced",
    "update": "memory_replaced",
    "edit": "memory_replaced",
    "remove": "memory_removed",
    "delete": "memory_removed",
}
_SKILL_ACTION_KIND = {
    "create": "skill_created",
    "created": "skill_created",
    "patch": "skill_patched",
    "edit": "skill_edited",
    "update": "skill_edited",
    "delete": "skill_deleted",
    "remove": "skill_deleted",
}


class Observer:
    def __init__(self, ledger: Ledger):
        self.ledger = ledger

    # -- memory --------------------------------------------------------------
    def on_memory_write(
        self,
        action: str,
        target: str,
        content: Optional[str] = None,
        *,
        before_text: Optional[str] = None,
        target_key: Optional[str] = None,
        target_path: Optional[str] = None,
        session_id: Optional[str] = None,
        tool_name: Optional[str] = "memory",
        source_hint: str = "plugin_hook",
        timestamp: Optional[float] = None,
        metadata: Optional[dict] = None,
        capture_window: bool = True,
    ) -> Optional[int]:
        """Record a memory add/replace/remove.

        ``target`` is the Hermes memory target ("user" or "memory"). Maps to
        ``target_type`` directly. ``action`` is the raw tool action.
        """
        try:
            kind = _MEMORY_ACTION_KIND.get((action or "").lower(), "memory_replaced")
            target_type = "user" if target == "user" else "memory"
            window = (
                provenance.capture_session_window(
                    self.ledger, session_id, around_ts=timestamp
                )
                if capture_window
                else None
            )
            return self.ledger.add_event(
                kind=kind,
                target_type=target_type,
                action=action,
                target_key=target_key,
                target_path=target_path,
                before_text=before_text,
                after_text=content,
                source_session_id=session_id,
                source_message_window=window,
                source_hint=source_hint,
                tool_name=tool_name,
                metadata=metadata,
                timestamp=timestamp,
            )
        except Exception:  # noqa: BLE001 - never let observation crash the caller
            log.exception("on_memory_write failed (action=%s target=%s)", action, target)
            return None

    # -- skill ---------------------------------------------------------------
    def on_skill_write(
        self,
        action: str,
        skill_name: str,
        *,
        content: Optional[str] = None,
        before_text: Optional[str] = None,
        file_path: Optional[str] = None,
        session_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        source_hint: str = "plugin_hook",
        timestamp: Optional[float] = None,
        metadata: Optional[dict] = None,
        capture_window: bool = True,
    ) -> Optional[int]:
        try:
            kind = _SKILL_ACTION_KIND.get((action or "").lower(), "skill_edited")
            window = (
                provenance.capture_session_window(
                    self.ledger, session_id, around_ts=timestamp
                )
                if capture_window
                else None
            )
            return self.ledger.add_event(
                kind=kind,
                target_type="skill",
                action=action,
                target_key=skill_name,
                target_path=file_path,
                before_text=before_text,
                after_text=content,
                source_session_id=session_id,
                source_message_window=window,
                source_hint=source_hint,
                tool_name=tool_name or "skill",
                metadata=metadata,
                timestamp=timestamp,
            )
        except Exception:  # noqa: BLE001
            log.exception("on_skill_write failed (action=%s skill=%s)", action, skill_name)
            return None
