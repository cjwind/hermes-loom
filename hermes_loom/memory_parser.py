"""Parse / serialize Hermes memory files (MEMORY.md, USER.md).

Real installs separate entries with a ``§`` line. We keep parsing tolerant:
entries are split on a line that is exactly ``§`` (optionally surrounded by
whitespace). Each entry maps to a stable key derived from its content hash so
the UI and overrides can address a specific entry even as ordering shifts.
"""

from __future__ import annotations

import hashlib
import re
from typing import List

SEP_LINE = re.compile(r"^\s*§\s*$", re.MULTILINE)


def entry_key(text: str) -> str:
    """Stable short key for an entry, based on its normalized content."""
    norm = text.strip()
    return "e" + hashlib.sha1(norm.encode("utf-8")).hexdigest()[:12]


def parse_entries(content: str) -> List[dict]:
    """Split file content into entries.

    Returns a list of ``{"index", "key", "text"}``. Empty fragments are skipped
    but a leading ``# Heading`` (if present) is treated as its own entry so the
    UI can show it. We keep this simple and robust.
    """
    if content is None:
        return []
    parts = SEP_LINE.split(content)
    entries = []
    idx = 0
    for part in parts:
        text = part.strip()
        if not text:
            continue
        entries.append({"index": idx, "key": entry_key(text), "text": text})
        idx += 1
    return entries


def serialize_entries(entries: List[dict]) -> str:
    """Rejoin entry dicts (or raw strings) back into file content."""
    texts = []
    for e in entries:
        texts.append(e["text"] if isinstance(e, dict) else str(e))
    body = "\n\n§\n".join(t.strip() for t in texts)
    return body + "\n" if body else ""


def find_entry(content: str, key: str) -> dict | None:
    for e in parse_entries(content):
        if e["key"] == key:
            return e
    return None
