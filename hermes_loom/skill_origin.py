"""Skill provenance / origin classification — the single source of truth.

A skill is classified from its SKILL.md frontmatter into one of three origins.
This logic lives here (a pure function) so it is never duplicated in the loader,
the service layer, or the UI. The loader computes it once; everything downstream
reads the resulting metadata.

Rules (frontmatter wins, highest priority first):

  1. ``created_by: agent``        → is_agent_created=True,  origin_type="agent_created"
  2. else, author is Hermes/Nous  → is_agent_created=False, origin_type="hermes_official"
  3. else (incl. missing/garbage) → is_agent_created=False, origin_type="community"

Everything is tolerant: missing frontmatter / fields never raise; the fallback
is always a sane value (not agent-created → community when the author is unknown).
"""

from __future__ import annotations

from typing import Optional

OriginType = str  # "agent_created" | "hermes_official" | "community"

# Authors that mark a skill as Hermes-official / native. Matched as a
# case-insensitive substring so compound credits still count, e.g.
# "Hermes Agent + Teknium", "…, ported by Hermes Agent", "0xbyt4, Hermes Agent".
# Extend this list to recognise more official author patterns.
HERMES_OFFICIAL_AUTHOR_PATTERNS = (
    "hermes agent",
    "nous research",
)


def _author_text(author) -> str:
    """Normalize an author field (str, list, or None) to a single string."""
    if author is None:
        return ""
    if isinstance(author, (list, tuple)):
        return ", ".join(str(a) for a in author)
    return str(author)


def is_hermes_official_author(author) -> bool:
    """True if the author credit identifies a Hermes-official / native source.

    Centralised so the official-author heuristic is defined in exactly one place.
    """
    text = _author_text(author).lower()
    if not text:
        return False
    return any(pat in text for pat in HERMES_OFFICIAL_AUTHOR_PATTERNS)


def classify_skill_origin(frontmatter: Optional[dict]) -> dict:
    """Classify a skill from its frontmatter dict.

    Returns ``{"is_agent_created": bool, "origin_type": OriginType,
               "author": str|None, "created_by": str|None}``.
    Pure and total: any input (None, {}, missing keys) yields a valid result.
    """
    fm = frontmatter or {}
    created_by_raw = fm.get("created_by")
    created_by = str(created_by_raw).strip().lower() if created_by_raw is not None else ""
    author_raw = fm.get("author")
    author = _author_text(author_raw) or None

    if created_by == "agent":
        origin = "agent_created"
        is_agent = True
    elif is_hermes_official_author(author_raw):
        origin = "hermes_official"
        is_agent = False
    else:
        origin = "community"
        is_agent = False

    return {
        "is_agent_created": is_agent,
        "origin_type": origin,
        "author": author,
        "created_by": (str(created_by_raw) if created_by_raw is not None else None),
    }


ORIGIN_LABELS = {
    "agent_created": "新沉澱（agent 產生）",
    "hermes_official": "Hermes 官方 / 原生",
    "community": "外部 / 社群",
}
