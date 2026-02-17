from typing import Any, Dict, List, Tuple

from .. import vllm_client
from .sanitize import sanitize_messages_limited
from .text_utils import _dedupe_repeated_response, _normalize_for_repeat_check, _strip_trailing_breaks


def _is_duplicate_of_assistant_history(response_text: Any, history: List[Dict[str, Any]]) -> bool:
    if not isinstance(response_text, str) or not response_text.strip():
        return False
    if not history:
        return False
    resp_norm = _normalize_for_repeat_check(response_text).lower()
    if not resp_norm:
        return False

    for m in history:
        if m.get("role") != "assistant":
            continue
        content = m.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        if _normalize_for_repeat_check(content).lower() == resp_norm:
            return True
    return False


async def _summarize_history_for_retry(history: List[Dict[str, Any]]) -> str:
    if not history:
        return ""

    history_lines: List[str] = []
    for m in history:
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        content = m.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        history_lines.append(f"{role.upper()}: {content.strip()}")

    if not history_lines:
        return ""

    summary = await vllm_client.get_vllm_response(
        [
            {
                "role": "system",
                "content": (
                    "Résume cette conversation en FR en 5-8 puces MAX. "
                    "Garde uniquement ce qui est utile pour répondre au prochain message. "
                    "Ne copie pas de phrases entières, reformule. Pas de meta."
                ),
            },
            {"role": "user", "content": "\n".join(history_lines)},
        ],
        temperature=0.3,
        top_p=0.9,
        max_tokens=220,
    )

    if not isinstance(summary, str):
        return ""
    return summary.strip()


async def _get_vllm_response_with_dup_retry(
    *,
    base_system_prompt: Dict[str, Any] | None,
    history: List[Dict[str, Any]],
    user_text: Any,
    stop: Any,
    temperature: float,
    top_p: float,
    max_tokens: int,
    max_dup_reprompts: int = 3,
) -> Tuple[str, Dict[str, Any]]:
    meta: Dict[str, Any] = {
        "dup_reprompts": 0,
        "used_summary": False,
        "history_summary": "",
        "history_debug_lines": [],
    }

    def _messages(
        system_msg: Dict[str, Any] | None,
        hist: List[Dict[str, Any]],
        text: Any,
    ) -> tuple[List[Dict[str, Any]], List[str]]:
        return sanitize_messages_limited(system_msg=system_msg, history=hist, user_text=text)

    system_prompt = base_system_prompt
    messages_for_llm, history_debug_lines = _messages(system_prompt, history, user_text)
    meta["history_debug_lines"] = history_debug_lines

    response_text = await vllm_client.get_vllm_response(
        messages_for_llm,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        stop=stop,
    )
    response_text = _dedupe_repeated_response(response_text)
    response_text = _strip_trailing_breaks(response_text)

    for i in range(max_dup_reprompts):
        if not _is_duplicate_of_assistant_history(response_text, history):
            return response_text, meta

        meta["dup_reprompts"] = i + 1
        retry_system_prompt = {
            "role": "system",
            "content": (
                (system_prompt or {}).get("content", "")
                + "\n\n<RETRY_OVERRIDE>\n"
                + "IMPORTANT: Ta dernière réponse est IDENTIQUE à une réponse précédente.\n"
                + "Réécris une nouvelle réponse différente, même intention, même personnage, sans copier-coller.\n"
                + "Garde un style chat (1-3 phrases), pas de meta.\n"
                + "</RETRY_OVERRIDE>"
            ),
        }

        messages_for_llm, history_debug_lines = _messages(retry_system_prompt, history, user_text)
        meta["history_debug_lines"] = history_debug_lines
        response_text = await vllm_client.get_vllm_response(
            messages_for_llm,
            temperature=max(0.75, float(temperature) + 0.1),
            top_p=top_p,
            max_tokens=max_tokens,
            stop=stop,
        )
        response_text = _dedupe_repeated_response(response_text)
        response_text = _strip_trailing_breaks(response_text)

    summary = await _summarize_history_for_retry(history)
    if summary:
        meta["used_summary"] = True
        meta["history_summary"] = summary
        summarized_system_prompt = {
            "role": "system",
            "content": (
                (system_prompt or {}).get("content", "")
                + "\n\n<CONTEXT_SUMMARY>\n"
                + summary
                + "\n</CONTEXT_SUMMARY>\n"
                + "\n<RETRY_OVERRIDE>\n"
                + "Ta dernière réponse boucle. En te basant sur le résumé ci-dessus, réponds avec un message nouveau.\n"
                + "Toujours court (1-3 phrases), pas de meta.\n"
                + "</RETRY_OVERRIDE>"
            ),
        }

        messages_for_llm, history_debug_lines = _messages(summarized_system_prompt, [], user_text)
        meta["history_debug_lines"] = history_debug_lines
        response_text = await vllm_client.get_vllm_response(
            messages_for_llm,
            temperature=max(0.75, float(temperature) + 0.15),
            top_p=top_p,
            max_tokens=max_tokens,
            stop=stop,
        )
        response_text = _dedupe_repeated_response(response_text)
        response_text = _strip_trailing_breaks(response_text)

    return response_text, meta
