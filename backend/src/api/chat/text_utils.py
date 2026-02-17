import re
from typing import Any, Dict, List


def _normalize_for_repeat_check(s: str) -> str:
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _has_repeated_word_ngrams(text: str, n: int = 6, min_hits: int = 2) -> bool:
    t = _normalize_for_repeat_check(text).lower()
    words = re.findall(r"\w+", t, flags=re.UNICODE)
    if len(words) < (n * 2):
        return False
    seen: Dict[str, int] = {}
    for i in range(0, len(words) - n + 1):
        gram = " ".join(words[i : i + n])
        seen[gram] = seen.get(gram, 0) + 1
        if seen[gram] >= min_hits:
            return True
    return False


def _dedupe_repeated_sentences(text: str) -> str:
    sentences = [s.strip() for s in re.split(r"(?<=[\.!?…])\s+", text.strip()) if s.strip()]
    if len(sentences) <= 1:
        return text.strip()

    seen_norm: set[str] = set()
    out: List[str] = []
    for s in sentences:
        ns = _normalize_for_repeat_check(s).lower()
        if not ns:
            continue
        if ns in seen_norm:
            continue
        seen_norm.add(ns)
        out.append(s)

    if not out:
        return text.strip()
    if len(out) == len(sentences):
        return text.strip()
    return " ".join(out).strip()


def _dedupe_repeated_response(text: Any) -> Any:
    if not isinstance(text, str) or not text.strip():
        return text

    s = text.strip()
    n = len(s)
    for k in (4, 3, 2):
        if n % k != 0:
            continue
        chunk_len = n // k
        chunks = [s[i * chunk_len : (i + 1) * chunk_len] for i in range(k)]
        norm0 = _normalize_for_repeat_check(chunks[0])
        if norm0 and all(_normalize_for_repeat_check(c) == norm0 for c in chunks[1:]):
            return chunks[0].strip()

    normalized = re.sub(r"<br\s*/?>", "\n", s, flags=re.IGNORECASE)
    parts = [p.strip() for p in re.split(r"\n\s*\n", normalized) if p.strip()]
    out: List[str] = []
    prev = ""
    for p in parts:
        np = _normalize_for_repeat_check(p)
        if not np:
            continue
        if np == prev:
            continue
        out.append(p)
        prev = np

    if len(out) <= 1:
        if _has_repeated_word_ngrams(s, n=6, min_hits=2):
            return _dedupe_repeated_sentences(s)
        return s

    candidate = "\n\n".join(out).strip()
    if _has_repeated_word_ngrams(candidate, n=6, min_hits=2):
        candidate = _dedupe_repeated_sentences(candidate)
    return candidate


def _strip_trailing_breaks(text: Any) -> Any:
    if not isinstance(text, str) or not text:
        return text
    s = text.strip()
    s = re.sub(r"(?:\s|<br\s*/?>)+\s*$", "", s, flags=re.IGNORECASE)
    return s.strip()


def _looks_like_refusal(text: Any) -> bool:
    if not isinstance(text, str):
        return False
    t = _normalize_for_repeat_check(text).lower()
    if not t:
        return False
    needles = (
        "désolé, mais je ne peux pas",
        "desole, mais je ne peux pas",
        "je ne peux pas répondre",
        "je ne peux pas repondre",
        "je ne peux pas répondre à",
        "je ne peux pas repondre a",
        "je ne peux pas t'aider",
        "je ne peux pas vous aider",
        "i can't help with",
        "i cannot help with",
        "i can't comply",
        "i cannot comply",
        "i'm sorry, but i can't",
        "i am sorry, but i can't",
    )
    return any(n in t for n in needles)


def _looks_like_only_emojis_or_punct(x: Any) -> bool:
    if not isinstance(x, str):
        return False
    s = x.strip()
    if not s:
        return True
    return re.search(r"[A-Za-z0-9À-ÖØ-öø-ÿ]", s) is None
