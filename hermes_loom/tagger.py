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
import urllib.error
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


def _post_chat(url: str, headers: dict, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:400]
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(f"HTTP {e.code}: {body}") from e


def _chat_complete(sys_prompt: str, user: str) -> str:
    """One OpenAI-compatible chat call → the assistant's text content.

    Handles param-shape compatibility: newer OpenAI models (gpt-5/o-series/4o)
    require ``max_completion_tokens`` and reject ``temperature`` != 1; older /
    other endpoints only know ``max_tokens``. Try modern first, fall back on 400.
    """
    base = os.environ["LOOM_LLM_BASE_URL"].rstrip("/")
    model = os.environ["LOOM_LLM_MODEL"]
    key = os.environ.get("LOOM_LLM_API_KEY", "")
    max_toks = int(os.environ.get("LOOM_LLM_MAX_TOKENS", "1024"))
    url = base + "/chat/completions"
    base_payload = {
        "model": model,
        "messages": [{"role": "system", "content": sys_prompt},
                     {"role": "user", "content": user}],
    }
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    variants = [
        {**base_payload, "max_completion_tokens": max_toks},
        {**base_payload, "max_tokens": max_toks, "temperature": 0},
    ]
    last_err = None
    for v in variants:
        try:
            body = _post_chat(url, headers, v)
            return (body.get("choices") or [{}])[0].get("message", {}).get("content", "")
        except RuntimeError as e:
            last_err = e
            if " 400:" in str(e):
                continue  # likely a param-shape mismatch; try the other variant
            raise
    if last_err:
        raise last_err
    return ""


def _resolve_llm(message: str, tags: List[str]) -> Optional[List[str]]:
    sys_prompt = (
        "You map a user message to relevant tags. You are given a fixed list of "
        "allowed tags. Return ONLY a compact JSON array of the tags (verbatim from "
        "the list) that are semantically relevant to the message. Return [] if none. "
        "No prose, no code fences."
    )
    user = "Allowed tags: " + json.dumps(tags, ensure_ascii=False) + "\nMessage: " + message
    content = _chat_complete(sys_prompt, user)
    picked = _parse_tag_array(content)
    allowed = {t.lower(): t for t in tags}
    return [allowed[p.lower()] for p in picked if p.lower() in allowed]


# ---- pack-aware selection (title + tags + "適用時機" → which packs to inject) --

def select_packs(message: str, packs: List[dict]) -> Tuple[List[int], str]:
    """Pick which packs to inject for a message. Returns (pack_ids, method).

    ``packs``: dicts with ``id``, ``title``, ``tags`` (list), ``when_to_use`` (str).
    LLM path weighs each pack's title + tags + when_to_use semantically; the
    keyword fallback selects a pack when its title or any tag is a substring of
    the message.
    """
    packs = [p for p in (packs or []) if p.get("id") is not None]
    if not message or not packs:
        return [], "none"
    if llm_configured():
        try:
            picked = _select_packs_llm(message, packs)
            if picked is not None:
                return picked, "llm"
        except Exception as e:  # noqa: BLE001 - fall back, never raise into the hook
            log.warning("LLM pack select failed (%s); falling back to keyword", e)
    return _select_packs_keyword(message, packs), "keyword"


def _select_packs_keyword(message: str, packs: List[dict]) -> List[int]:
    m = message.lower()
    out = []
    for p in packs:
        title = (p.get("title") or "").lower()
        tags = [str(t).lower() for t in (p.get("tags") or [])]
        if (title and title in m) or any(t and t in m for t in tags):
            out.append(p["id"])
    return out


def _select_packs_llm(message: str, packs: List[dict]) -> Optional[List[int]]:
    lines = []
    for p in packs:
        desc = '#' + str(p["id"]) + ' title=' + json.dumps(p.get("title") or "", ensure_ascii=False)
        if p.get("tags"):
            desc += ' tags=' + json.dumps(p["tags"], ensure_ascii=False)
        if p.get("when_to_use"):
            desc += ' when_to_use=' + json.dumps(p["when_to_use"], ensure_ascii=False)
        lines.append(desc)
    sys_prompt = (
        "You decide which memory packs are relevant to inject as context for a "
        "user message. You are given a list of packs, each with an id, title, "
        "optional tags, and an optional 'when_to_use' note describing the "
        "situations the pack applies to. Weigh all three. Return ONLY a compact "
        "JSON array of the integer ids of the packs that apply to the message. "
        "Return [] if none. No prose, no code fences."
    )
    user = "Packs:\n" + "\n".join(lines) + "\nMessage: " + message
    content = _chat_complete(sys_prompt, user)
    picked = _parse_tag_array(content)
    valid = {int(p["id"]) for p in packs}
    out = []
    for x in picked:
        try:
            i = int(str(x).strip().lstrip("#"))
        except (ValueError, TypeError):
            continue
        if i in valid and i not in out:
            out.append(i)
    return out


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
