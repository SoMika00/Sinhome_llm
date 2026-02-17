import re
from typing import Any, Dict, List

from .text_utils import _looks_like_only_emojis_or_punct, _normalize_for_repeat_check


def _merge_content(c1: Any, c2: Any) -> Any:
    if isinstance(c1, list) or isinstance(c2, list):
        l1 = c1 if isinstance(c1, list) else [{"type": "text", "text": str(c1)}]
        l2 = c2 if isinstance(c2, list) else [{"type": "text", "text": str(c2)}]
        return l1 + l2
    s1 = (c1 or "").strip() if isinstance(c1, str) else ("" if c1 is None else str(c1))
    s2 = (c2 or "").strip() if isinstance(c2, str) else ("" if c2 is None else str(c2))
    if not s1:
        return s2
    if not s2:
        return s1
    return f"{s1}\n{s2}"


def sanitize_messages(system_msg: Dict[str, Any] | None, history: List[Dict[str, Any]], user_text: Any) -> List[Dict[str, Any]]:
    msgs: List[Dict[str, Any]] = []

    if system_msg and system_msg.get("role") == "system":
        msgs.append({"role": "system", "content": system_msg.get("content", "")})

    collapsed: List[Dict[str, Any]] = []
    for m in history:
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        content = m.get("content")
        if content is None or (isinstance(content, str) and not content.strip()):
            continue
        if collapsed and collapsed[-1]["role"] == role:
            collapsed[-1]["content"] = _merge_content(collapsed[-1]["content"], content)
        else:
            collapsed.append({"role": role, "content": content})

    if collapsed and collapsed[-1]["role"] == "user":
        last = collapsed[-1].get("content")
        if isinstance(last, str) and isinstance(user_text, str) and last.strip() == user_text.strip():
            pass
        else:
            collapsed[-1]["content"] = _merge_content(last, user_text)
    else:
        collapsed.append({"role": "user", "content": user_text})

    msgs.extend(collapsed)
    return msgs


def sanitize_messages_limited(
    system_msg: Dict[str, Any] | None,
    history: List[Dict[str, Any]],
    user_text: Any,
    couples_to_keep: int = 15,
    token_budget: int = 4000,
) -> tuple[List[Dict[str, Any]], List[str]]:
    kept_history, debug_lines = _select_history_last_couples_with_token_budget(
        history=history,
        couples_to_keep=couples_to_keep,
        token_budget=token_budget,
    )
    return sanitize_messages(system_msg=system_msg, history=kept_history, user_text=user_text), debug_lines


def _truncate_at_word_boundary(text: Any, max_chars: int) -> Any:
    if not isinstance(text, str):
        return text
    s = text.strip()
    if max_chars <= 0 or len(s) <= max_chars:
        return s

    cut = s[:max_chars]
    m = re.match(r"^(.*)\b\w+\b", cut)
    if m and m.group(1).strip():
        cut = m.group(1)
    cut = cut.rstrip()
    return cut


def _dedupe_similar_history(history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen_assistant: set[str] = set()
    out_rev: List[Dict[str, Any]] = []
    for m in reversed(history or []):
        role = m.get("role")
        content = m.get("content")
        if role == "assistant" and isinstance(content, str):
            key = _normalize_for_repeat_check(content)
            if key and key in seen_assistant:
                continue
            if key:
                seen_assistant.add(key)
        out_rev.append(m)
    out_rev.reverse()
    return out_rev


def _as_text_for_token_estimate(content: Any) -> str:
    if isinstance(content, list):
        parts: List[str] = []
        for p in content:
            if isinstance(p, dict) and p.get("type") == "text":
                parts.append(str(p.get("text", "")))
            elif isinstance(p, dict) and p.get("type") == "image_url":
                parts.append("[IMAGE]")
            else:
                parts.append(str(p))
        return " ".join([x for x in parts if x])
    if content is None:
        return ""
    return str(content)


def _estimate_tokens(text: str) -> int:
    s = (text or "").strip()
    if not s:
        return 0
    return max(1, (len(s) + 3) // 4)


def _select_history_last_couples_with_token_budget(
    history: List[Dict[str, Any]],
    couples_to_keep: int,
    token_budget: int,
) -> tuple[List[Dict[str, Any]], List[str]]:
    original: List[Dict[str, Any]] = list(history or [])
    if not original:
        return [], []

    deduped_history = _dedupe_similar_history(original)
    original_idx_by_id: Dict[int, int] = {id(m): i for i, m in enumerate(original)}
    filtered: List[tuple[int, Dict[str, Any]]] = []
    for m in deduped_history:
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        content = m.get("content")
        if content is None or (isinstance(content, str) and not content.strip()):
            continue
        if role == "assistant" and _looks_like_only_emojis_or_punct(content):
            continue
        idx = original_idx_by_id.get(id(m), -1)
        if idx < 0:
            continue
        if isinstance(content, str):
            content = _truncate_at_word_boundary(content, 300)
        filtered.append((idx, {"role": role, "content": content}))

    if not filtered:
        return [], []

    blocks: List[List[tuple[int, Dict[str, Any]]]] = []
    for idx, m in filtered:
        if not blocks or blocks[-1][0][1]["role"] != m["role"]:
            blocks.append([(idx, m)])
        else:
            blocks[-1].append((idx, m))

    couples: List[List[tuple[int, Dict[str, Any]]]] = []
    i = len(blocks) - 1
    while i >= 1 and len(couples) < couples_to_keep:
        couples.append(blocks[i - 1] + blocks[i])
        i -= 2
    couples.reverse()

    candidates: List[tuple[int, Dict[str, Any]]] = []
    for c in couples:
        candidates.extend(c)

    kept_rev: List[tuple[int, Dict[str, Any]]] = []
    used_tokens = 0
    for idx, m in reversed(candidates):
        content_text = _as_text_for_token_estimate(m.get("content"))
        t = _estimate_tokens(content_text)
        if token_budget > 0 and used_tokens + t > token_budget:
            continue
        kept_rev.append((idx, m))
        used_tokens += t
    kept_with_idx = list(reversed(kept_rev))
    kept = [m for _, m in kept_with_idx]
    kept_indices = {idx for idx, _ in kept_with_idx}

    debug_lines: List[str] = []
    if original:
        for idx, m in enumerate(original):
            role = str(m.get("role", "unknown")).upper()
            content_text = _as_text_for_token_estimate(m.get("content"))
            content_text = _truncate_at_word_boundary(content_text, 300) if isinstance(content_text, str) else str(content_text)
            tag = "KEPT" if idx in kept_indices else "DROPPED"
            debug_lines.append(f"[{tag}][{idx}][{role}]: {content_text}")

    return kept, debug_lines


def _trim_history_last_couples(history: List[Dict[str, Any]], couples_to_keep: int) -> List[Dict[str, Any]]:
    if couples_to_keep <= 0:
        return []

    deduped_history = _dedupe_similar_history(history)
    filtered: List[Dict[str, Any]] = []
    for m in deduped_history:
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        content = m.get("content")
        if content is None or (isinstance(content, str) and not content.strip()):
            continue
        if role == "assistant" and _looks_like_only_emojis_or_punct(content):
            continue
        if isinstance(content, str):
            content = _truncate_at_word_boundary(content, 300)
        filtered.append({"role": role, "content": content})

    if not filtered:
        return []

    blocks: List[List[Dict[str, Any]]] = []
    for m in filtered:
        if not blocks or blocks[-1][0]["role"] != m["role"]:
            blocks.append([m])
        else:
            blocks[-1].append(m)

    couples: List[List[Dict[str, Any]]] = []
    i = len(blocks) - 1
    while i >= 1 and len(couples) < couples_to_keep:
        couples.append(blocks[i - 1] + blocks[i])
        i -= 2
    couples.reverse()

    trimmed: List[Dict[str, Any]] = []
    for c in couples:
        trimmed.extend(c)
    return trimmed


def sanitize_messages_script(system_msg: Dict[str, Any] | None, history: List[Dict[str, Any]], user_text: Any, couples_to_keep: int = 5) -> List[Dict[str, Any]]:
    msgs: List[Dict[str, Any]] = []

    if system_msg and system_msg.get("role") == "system":
        msgs.append({"role": "system", "content": system_msg.get("content", "")})

    trimmed_history = _trim_history_last_couples(history, couples_to_keep)
    msgs.extend(trimmed_history)

    if msgs and msgs[-1].get("role") == "user":
        last = msgs[-1].get("content")
        if isinstance(last, str) and isinstance(user_text, str) and last.strip() == user_text.strip():
            return msgs

    msgs.append({"role": "user", "content": user_text})
    return msgs
