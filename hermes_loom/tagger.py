"""Resolve which tags a user message is about.

Used by the pre_llm_call recall hook: given the user's chat message and the set
of tags that exist in Loom, decide which tags are semantically relevant.

Two strategies, in order:
  1. **LLM** (semantic) — when an OpenAI-compatible endpoint is configured via env
     (LOOM_LLM_BASE_URL + LOOM_LLM_MODEL, optional LOOM_LLM_API_KEY). We ask it to
     pick the relevant tags from the provided list and return a JSON array.
  2. **Keyword fallback** — substring match of each tag (and the message) when no
     LLM is configured, or if the LLM call fails/times out. Always safe & offline.

stdlib only (urllib) so it runs inside the Hermes gateway process with no extra
deps. The call is bounded by a short timeout so it never stalls a turn.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import List, Optional, Tuple

log = logging.getLogger("hermes_loom.tagger")

_TIMEOUT = float(os.environ.get("LOOM_LLM_TIMEOUT", "8"))


def llm_configured() -> bool:
    return bool(os.environ.get("LOOM_LLM_BASE_URL") and os.environ.get("LOOM_LLM_MODEL"))


def diagnose(probe: bool = False) -> dict:
    """Report whether the LLM endpoint is configured (no secrets exposed).

    With ``probe=True`` it makes one real test call so you can see the actual
    error when ``method`` keeps coming back "keyword" despite config.
    """
    out = {
        "configured": llm_configured(),
        "base_url": os.environ.get("LOOM_LLM_BASE_URL"),
        "model": os.environ.get("LOOM_LLM_MODEL"),
        "has_api_key": bool(os.environ.get("LOOM_LLM_API_KEY")),
        "timeout": _TIMEOUT,
    }
    if probe and out["configured"]:
        try:
            picked = _resolve_llm("I'm planning dinner, any food notes?", ["food", "travel"])
            out["probe"] = {"ok": True, "picked": picked}
        except Exception as e:  # noqa: BLE001
            out["probe"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return out


def resolve_tags(message: str, tags: List[str]) -> Tuple[List[str], str]:
    """Return (matched_tags, method). method ∈ {"llm","keyword","none"}."""
    tags = [t for t in (tags or []) if t]
    if not message or not tags:
        return [], "none"
    if llm_configured():
        try:
            picked = _resolve_llm(message, tags)
            if picked is not None:
                return picked, "llm"
        except Exception as e:  # noqa: BLE001 - fall back, never raise into the hook
            log.warning("LLM tag resolve failed (%s); falling back to keyword", e)
    return _resolve_keyword(message, tags), "keyword"


def _resolve_keyword(message: str, tags: List[str]) -> List[str]:
    m = message.lower()
    return [t for t in tags if t.lower() in m]


def _resolve_llm(message: str, tags: List[str]) -> Optional[List[str]]:
    base = os.environ["LOOM_LLM_BASE_URL"].rstrip("/")
    model = os.environ["LOOM_LLM_MODEL"]
    key = os.environ.get("LOOM_LLM_API_KEY", "")
    url = base + "/chat/completions"
    sys_prompt = (
        "You map a user message to relevant tags. You are given a fixed list of "
        "allowed tags. Return ONLY a compact JSON array of the tags (verbatim from "
        "the list) that are semantically relevant to the message. Return [] if none. "
        "No prose, no code fences."
    )
    user = "Allowed tags: " + json.dumps(tags, ensure_ascii=False) + "\nMessage: " + message
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": sys_prompt},
                     {"role": "user", "content": user}],
        "temperature": 0,
        "max_tokens": 200,
    }
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        body = json.loads(resp.read())
    content = (body.get("choices") or [{}])[0].get("message", {}).get("content", "")
    picked = _parse_tag_array(content)
    allowed = {t.lower(): t for t in tags}
    return [allowed[p.lower()] for p in picked if p.lower() in allowed]


def _parse_tag_array(content: str) -> List[str]:
    """Extract a JSON array of strings from the model output (tolerant)."""
    if not content:
        return []
    s = content.strip()
    if s.startswith("```"):
        s = s.strip("`")
        s = s[s.find("\n") + 1:] if "\n" in s else s
    start, end = s.find("["), s.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        arr = json.loads(s[start:end + 1])
        return [str(x) for x in arr] if isinstance(arr, list) else []
    except (json.JSONDecodeError, TypeError):
        return []
