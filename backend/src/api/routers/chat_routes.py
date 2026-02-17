import asyncio
import logging
import time
import uuid
from typing import Any, Dict, List

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import settings
from ..services import vllm_client
from ..services.conversation_logger import log_conversation, log_error
from ..services.persona_builder import (
    FALLBACK_PERSONALITY_DATA,
    PersonaSettings,
    build_dynamic_system_prompt,
    build_followup_system_prompt,
)
from ..services.unpersona_builder import FALLBACK_NAME, build_baseline_chat_prompt
from ..services.script_unpersona_builder import build_script_chat_prompt
from ..services.grok_client import get_grok_response, get_grok_completion
from ..services.chat.retry import _get_vllm_response_with_dup_retry
from ..services.chat.sanitize import sanitize_messages
from ..services.chat.sanitize import sanitize_messages_limited
from ..services.chat.sanitize import sanitize_messages_script
from ..services.chat.schemas import (
    ChatResponse,
    DirectChatRequest,
    PersonalityChatRequest,
    ScriptChatRequest,
    UnpersonaChatRequest,
)
from ..services.chat.text_utils import (
    _dedupe_repeated_response,
    _looks_like_refusal,
    _strip_trailing_breaks,
)


ext_router = APIRouter()

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)


class OpenAIChatCompletionsRequest(BaseModel):
    model: str | None = None
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stop: Any | None = None
    tools: Any | None = None
    tool_choice: Any | None = None
    stream: bool | None = None


def _as_int(x: Any, default: int) -> int:
    try:
        v = int(x)
        return v if 1 <= v <= 5 else default
    except (ValueError, TypeError):
        return default


def _persona_from_lambda_dict(d: Dict[str, Any]) -> PersonaSettings:
    return PersonaSettings(
        sales_tactic=_as_int(d.get("sales_tactic"), 2),
        dominance=_as_int(d.get("dominance"), 3),
        audacity=_as_int(d.get("audacity"), 3),
        tone=_as_int(d.get("tone"), 2),
        emotion=_as_int(d.get("emotion"), 3),
        initiative=_as_int(d.get("initiative"), 3),
        vocabulary=_as_int(d.get("vocabulary"), 3),
        emojis=_as_int(d.get("emojis"), 3),
        imperfection=_as_int(d.get("imperfection"), 1),
    )


@ext_router.post(
    "/direct_chat",
    response_model=ChatResponse,
    summary="Test direct - persona par defaut, pas d'historique",
)
async def direct_chat(request: DirectChatRequest):
    try:
        stop = request.stop
        temperature = request.temperature if request.temperature is not None else 0.65
        top_p = request.top_p if request.top_p is not None else 0.9
        max_tokens = request.max_tokens if request.max_tokens is not None else 256

        messages: List[Dict[str, Any]] = []
        if request.messages:
            messages = request.messages
        elif request.prompt is not None:
            messages = [{"role": "user", "content": str(request.prompt)}]
        elif request.message is not None:
            messages = [{"role": "user", "content": str(request.message)}]

        if not messages:
            raise HTTPException(
                status_code=422,
                detail="direct_chat: fournir soit 'messages', soit 'prompt', soit 'message'.",
            )

        safe_preview = ""
        try:
            last = messages[-1]
            safe_preview = str(last.get("content", ""))[:100]
        except Exception:
            safe_preview = ""

        logger.info("[direct_chat] last_user_preview: %s", safe_preview)

        if settings.SINHOME_LLM_BACKEND.lower() == "grok":
            response_text = await get_grok_response(
                messages,
                temperature=temperature,
                top_p=top_p,
                max_tokens=max_tokens,
                stop=stop,
            )
        else:
            response_text = await vllm_client.get_vllm_response(
                messages,
                temperature=temperature,
                top_p=top_p,
                max_tokens=max_tokens,
                stop=stop,
            )

        response_text = _dedupe_repeated_response(response_text)
        response_text = _strip_trailing_breaks(response_text)

        logger.info("[direct_chat] response (%d chars): %s...", len(response_text), str(response_text)[:100])

        asyncio.create_task(
            log_conversation(
                endpoint="/direct_chat",
                system_prompt="",
                history=messages[:-1],
                user_message=str(messages[-1].get("content", "")),
                ai_response=response_text,
                session_id=None,
                extra_info={
                    "history_selection": "(Stateless - payload only)",
                },
                raw_payload={
                    "message": request.message,
                    "prompt": request.prompt,
                    "messages": request.messages,
                    "temperature": temperature,
                    "top_p": top_p,
                    "max_tokens": max_tokens,
                    "stop": stop,
                },
            )
        )

        return ChatResponse(response=str(response_text))
    except httpx.ConnectError as e:
        logger.error("[direct_chat] LLM connection failed: %s", e)
        msg = (request.message or request.prompt or "")
        asyncio.create_task(log_error("/direct_chat", str(e), context={"message": str(msg)[:200]}))
        raise HTTPException(status_code=503, detail=f"Service LLM indisponible: {e}")
    except Exception as e:
        logger.exception("[direct_chat] internal error")
        msg = (request.message or request.prompt or "")
        asyncio.create_task(log_error("/direct_chat", str(e), context={"message": str(msg)[:200]}))
        raise HTTPException(status_code=500, detail=f"Erreur interne: {e}")


@ext_router.post("/v1/chat/completions")
async def openai_chat_completions(request: OpenAIChatCompletionsRequest):
    if request.stream:
        raise HTTPException(status_code=400, detail="stream=true non supporté")

    temperature = request.temperature if request.temperature is not None else 0.65
    top_p = request.top_p if request.top_p is not None else 0.9
    max_tokens = request.max_tokens if request.max_tokens is not None else 256
    stop = request.stop

    if not request.messages:
        raise HTTPException(status_code=422, detail="fournir 'messages'")

    messages = request.messages

    if settings.SINHOME_LLM_BACKEND.lower() == "grok":
        response_text = await get_grok_response(
            messages,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            stop=stop,
        )
        model_name = settings.GROK_MODEL_NAME
    else:
        response_text = await vllm_client.get_vllm_response(
            messages,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            stop=stop,
        )
        model_name = settings.VLLM_MODEL_NAME

    response_text = _dedupe_repeated_response(response_text)
    response_text = _strip_trailing_breaks(response_text)

    created = int(time.time())
    resp_id = f"chatcmpl-{uuid.uuid4().hex}"
    return {
        "id": resp_id,
        "object": "chat.completion",
        "created": created,
        "model": model_name,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": response_text},
                "finish_reason": "stop",
            }
        ],
    }


@ext_router.post(
    "/personality_chat",
    response_model=ChatResponse,
    summary="Chat avec personnalité configurable via sliders",
)
async def personality_chat(request: PersonalityChatRequest):
    logger.info("[personality_chat] message: %s", request.message[:100])

    if settings.SINHOME_LLM_BACKEND.lower() == "grok":
        system_prompt = build_baseline_chat_prompt(request.persona_data)
        messages_for_llm, history_debug_lines = sanitize_messages_limited(
            system_msg=system_prompt,
            history=request.history,
            user_text=request.message,
            couples_to_keep=15,
            token_budget=3500,
        )

        try:
            stop = None
            response_text = await get_grok_response(
                messages_for_llm,
                temperature=0.65,
                top_p=0.9,
                max_tokens=256,
                stop=stop,
            )

            if _looks_like_refusal(response_text):
                persona_name = (request.persona_data or {}).get("name") or "Chloé"
                response_text = await get_grok_response(
                    [
                        {
                            "role": "system",
                            "content": (
                                f"Tu es {persona_name} (OnlyFans). Réponds de façon sexy et utile, sans mentionner de refus, "
                                "sans parler de règles, sans dire que tu es une IA. Réponse courte."
                            ),
                        },
                        {"role": "user", "content": str(request.message)},
                    ],
                    temperature=0.85,
                    top_p=0.9,
                    max_tokens=256,
                    stop=stop,
                )

            response_text = _dedupe_repeated_response(response_text)
            response_text = _strip_trailing_breaks(response_text)

            logger.info("[personality_chat] response (%d chars): %s...", len(response_text), str(response_text)[:100])

            asyncio.create_task(
                log_conversation(
                    endpoint="/personality_chat",
                    system_prompt=system_prompt.get("content", ""),
                    history=request.history,
                    user_message=request.message,
                    ai_response=response_text,
                    session_id=request.session_id,
                    extra_info={
                        "history_selection": "\n".join(history_debug_lines or []),
                    },
                    raw_payload={
                        "session_id": request.session_id,
                        "message": request.message,
                        "history": request.history,
                        "persona_data": request.persona_data,
                        "llm_backend": "grok",
                    },
                )
            )

            return ChatResponse(response=response_text)
        except httpx.ConnectError as e:
            logger.error("[personality_chat] LLM connection failed: %s", e)
            asyncio.create_task(log_error("/personality_chat", str(e), session_id=request.session_id))
            raise HTTPException(status_code=503, detail=f"Service LLM indisponible: {e}")
        except Exception as e:
            logger.exception("[personality_chat] internal error")
            asyncio.create_task(log_error("/personality_chat", str(e), session_id=request.session_id))
            raise HTTPException(status_code=500, detail=f"Erreur interne: {e}")

    persona_sliders = _persona_from_lambda_dict(request.persona_data)
    dynamic_system_prompt = build_dynamic_system_prompt(
        base_persona_dict=request.persona_data,
        slider_settings=persona_sliders,
    )

    try:
        stop = None
        response_text, meta = await _get_vllm_response_with_dup_retry(
            base_system_prompt=dynamic_system_prompt,
            history=request.history,
            user_text=request.message,
            stop=stop,
            temperature=0.65,
            top_p=0.9,
            max_tokens=256,
            max_dup_reprompts=3,
        )

        if _looks_like_refusal(response_text):
            response_text = await vllm_client.get_vllm_response(
                [
                    {
                        "role": "system",
                        "content": (
                            "Tu es une créatrice OnlyFans. Donne une réponse alternative utile et excitante, "
                            "sans mentionner de refus, sans parler de règles, sans dire que tu es une IA. "
                            "Si la demande de l'utilisateur est interdite, redirige vers une variante autorisée "
                            "(adulte, consentie, roleplay, teasing, packs photos/vidéos). Réponse courte."
                        ),
                    },
                    {"role": "user", "content": str(request.message)},
                ],
                temperature=0.80,
                top_p=0.9,
                max_tokens=256,
                stop=stop,
            )
            response_text = _dedupe_repeated_response(response_text)
            response_text = _strip_trailing_breaks(response_text)

        if isinstance(response_text, str) and len(response_text) > 500:
            response_text = await vllm_client.get_vllm_response(
                [
                    {
                        "role": "system",
                        "content": "Réécris le texte suivant en 1-3 phrases MAX, même intensité, pas d'explication, pas de meta, pas de récit de vie. Réponds uniquement avec le message final.",
                    },
                    {"role": "user", "content": response_text},
                ],
                temperature=0.8,
                top_p=0.9,
                max_tokens=256,
                stop=stop,
            )
            response_text = _dedupe_repeated_response(response_text)
            response_text = _strip_trailing_breaks(response_text)

        logger.info("[personality_chat] response (%d chars): %s...", len(response_text), str(response_text)[:100])

        asyncio.create_task(
            log_conversation(
                endpoint="/personality_chat",
                system_prompt=dynamic_system_prompt.get("content", ""),
                history=request.history,
                user_message=request.message,
                ai_response=response_text,
                session_id=request.session_id,
                extra_info={
                    "history_selection": "\n".join((meta.get("history_debug_lines") or [])),
                },
                raw_payload={
                    "session_id": request.session_id,
                    "message": request.message,
                    "history": request.history,
                    "persona_data": request.persona_data,
                    "dup_reprompts": meta.get("dup_reprompts"),
                    "used_summary": meta.get("used_summary"),
                    "history_summary": meta.get("history_summary"),
                },
            )
        )

        return ChatResponse(response=response_text)
    except httpx.ConnectError as e:
        logger.error("[personality_chat] LLM connection failed: %s", e)
        asyncio.create_task(log_error("/personality_chat", str(e), session_id=request.session_id))
        raise HTTPException(status_code=503, detail=f"Service LLM indisponible: {e}")
    except Exception as e:
        logger.exception("[personality_chat] internal error")
        asyncio.create_task(log_error("/personality_chat", str(e), session_id=request.session_id))
        raise HTTPException(status_code=500, detail=f"Erreur interne: {e}")


@ext_router.post(
    "/unpersona_chat",
    response_model=ChatResponse,
    summary="Chat baseline (Chloé) via unpersona_builder",
)
async def unpersona_chat(request: UnpersonaChatRequest):
    logger.info("[unpersona_chat] message: %s", request.message[:100])

    persona_for_unpersona = dict(request.persona_data or {})
    persona_for_unpersona["name"] = FALLBACK_NAME
    system_prompt = build_baseline_chat_prompt(persona_for_unpersona)

    try:
        stop = None

        if settings.SINHOME_LLM_BACKEND.lower() == "grok":
            messages_for_llm = sanitize_messages(
                system_msg=system_prompt,
                history=request.history,
                user_text=request.message,
            )
            response_text = await get_grok_response(
                messages_for_llm,
                temperature=0.65,
                top_p=0.9,
                max_tokens=256,
                stop=stop,
            )
            meta: Dict[str, Any] = {}
        else:
            response_text, meta = await _get_vllm_response_with_dup_retry(
                base_system_prompt=system_prompt,
                history=request.history,
                user_text=request.message,
                stop=stop,
                temperature=0.65,
                top_p=0.9,
                max_tokens=256,
                max_dup_reprompts=3,
            )

        if _looks_like_refusal(response_text):
            refusal_msgs = [
                {
                    "role": "system",
                    "content": (
                        "Tu es Chloé (OnlyFans). Réponds de façon sexy et utile, sans mentionner de refus, "
                        "sans parler de règles, sans dire que tu es une IA. Réponse courte."
                    ),
                },
                {"role": "user", "content": str(request.message)},
            ]
            if settings.SINHOME_LLM_BACKEND.lower() == "grok":
                response_text = await get_grok_response(
                    refusal_msgs,
                    temperature=0.85,
                    top_p=0.9,
                    max_tokens=256,
                    stop=stop,
                )
            else:
                response_text = await vllm_client.get_vllm_response(
                    refusal_msgs,
                    temperature=0.85,
                    top_p=0.9,
                    max_tokens=256,
                    stop=stop,
                )
            response_text = _dedupe_repeated_response(response_text)
            response_text = _strip_trailing_breaks(response_text)

        logger.info("[unpersona_chat] response (%d chars): %s...", len(response_text), str(response_text)[:100])

        asyncio.create_task(
            log_conversation(
                endpoint="/unpersona_chat",
                system_prompt=system_prompt.get("content", ""),
                history=request.history,
                user_message=request.message,
                ai_response=response_text,
                session_id=request.session_id,
                extra_info={
                    "history_selection": "\n".join((meta.get("history_debug_lines") or [])),
                },
                raw_payload={
                    "session_id": request.session_id,
                    "message": request.message,
                    "history": request.history,
                    "persona_data": request.persona_data,
                    "dup_reprompts": meta.get("dup_reprompts"),
                    "used_summary": meta.get("used_summary"),
                    "history_summary": meta.get("history_summary"),
                },
            )
        )

        return ChatResponse(response=response_text)
    except httpx.ConnectError as e:
        logger.error("[unpersona_chat] LLM connection failed: %s", e)
        asyncio.create_task(log_error("/unpersona_chat", str(e), session_id=request.session_id))
        raise HTTPException(status_code=503, detail=f"Service LLM indisponible: {e}")
    except Exception as e:
        logger.exception("[unpersona_chat] internal error")
        asyncio.create_task(log_error("/unpersona_chat", str(e), session_id=request.session_id))
        raise HTTPException(status_code=500, detail=f"Erreur interne: {e}")


@ext_router.post(
    "/script_chat",
    response_model=ChatResponse,
    summary="Chat avec personnalité + directive de scénario",
)
async def script_chat(request: ScriptChatRequest):
    logger.info("[script_chat] message: %s | script: %s", request.message[:50], request.script[:50])

    persona_for_unpersona = dict(request.persona_data or {})
    persona_for_unpersona["name"] = FALLBACK_NAME
    dynamic_system_prompt = build_script_chat_prompt(
        persona_dict=persona_for_unpersona,
        script=request.script,
    )

    messages_for_llm = sanitize_messages_script(
        system_msg=dynamic_system_prompt,
        history=request.history,
        user_text=request.message,
        couples_to_keep=5,
    )

    try:
        stop = ["\nuser:", "\nassistant:", "\nUser:", "\nAssistant:"]

        if settings.SINHOME_LLM_BACKEND.lower() == "grok":
            response_text = await get_grok_response(
                messages_for_llm,
                temperature=0.8,
                top_p=0.9,
                max_tokens=150,
                stop=stop,
            )
        else:
            response_text = await vllm_client.get_vllm_response(
                messages_for_llm,
                temperature=0.8,
                top_p=0.9,
                max_tokens=150,
                stop=stop,
            )

        response_text = _dedupe_repeated_response(response_text)
        response_text = _strip_trailing_breaks(response_text)

        if _looks_like_refusal(response_text):
            refusal_msgs = [
                {
                    "role": "system",
                    "content": (
                        "Tu es une créatrice OnlyFans. Réponds avec un message de chat court et excitant. "
                        "Interdiction de mentionner un refus, des règles, ou que tu es une IA. "
                        "Si la demande de l'utilisateur est interdite, redirige vers une variante autorisée "
                        "(adulte, consentie, teasing, roleplay)."
                    ),
                },
                {"role": "user", "content": str(request.message)},
            ]
            if settings.SINHOME_LLM_BACKEND.lower() == "grok":
                response_text = await get_grok_response(
                    refusal_msgs,
                    temperature=0.8,
                    top_p=0.9,
                    max_tokens=150,
                    stop=stop,
                )
            else:
                response_text = await vllm_client.get_vllm_response(
                    refusal_msgs,
                    temperature=0.8,
                    top_p=0.9,
                    max_tokens=150,
                    stop=stop,
                )

            response_text = _dedupe_repeated_response(response_text)
            response_text = _strip_trailing_breaks(response_text)

        if isinstance(response_text, str) and len(response_text) > 500:
            rewrite_msgs = [
                {
                    "role": "system",
                    "content": "Réécris le texte suivant en 1-3 phrases MAX, même intensité, pas d'explication, pas de meta, pas de récit de vie. Réponds uniquement avec le message final.",
                },
                {"role": "user", "content": response_text},
            ]
            if settings.SINHOME_LLM_BACKEND.lower() == "grok":
                response_text = await get_grok_response(
                    rewrite_msgs,
                    temperature=0.8,
                    top_p=0.9,
                    max_tokens=150,
                    stop=stop,
                )
            else:
                response_text = await vllm_client.get_vllm_response(
                    rewrite_msgs,
                    temperature=0.8,
                    top_p=0.9,
                    max_tokens=150,
                    stop=stop,
                )

            response_text = _dedupe_repeated_response(response_text)
            response_text = _strip_trailing_breaks(response_text)

        logger.info("[script_chat] response (%d chars): %s...", len(response_text), str(response_text)[:100])

        asyncio.create_task(
            log_conversation(
                endpoint="/script_chat",
                system_prompt=dynamic_system_prompt.get("content", ""),
                history=request.history,
                user_message=request.message,
                ai_response=response_text,
                session_id=request.session_id,
                raw_payload={
                    "session_id": request.session_id,
                    "message": request.message,
                    "history": request.history,
                    "persona_data": request.persona_data,
                    "script": request.script,
                },
            )
        )

        return ChatResponse(response=response_text)
    except httpx.ConnectError as e:
        logger.error("[script_chat] LLM connection failed: %s", e)
        asyncio.create_task(log_error("/script_chat", str(e), session_id=request.session_id))
        raise HTTPException(status_code=503, detail=f"Service LLM indisponible: {e}")
    except Exception as e:
        logger.exception("[script_chat] internal error")
        asyncio.create_task(log_error("/script_chat", str(e), session_id=request.session_id))
        raise HTTPException(status_code=500, detail=f"Erreur interne: {e}")


@ext_router.post(
    "/script_followup",
    response_model=ChatResponse,
    summary="Relance: même payload que /script_chat, message = consigne de follow up",
)
@ext_router.post(
    "/script_folowup",
    response_model=ChatResponse,
    summary="(Alias) Relance: même payload que /script_chat, message = consigne de follow up",
)
async def script_followup(request: ScriptChatRequest):
    logger.info("[script_followup] followup_instruction (message): %s | script: %s", request.message[:50], request.script[:50])

    persona_sliders = _persona_from_lambda_dict(request.persona_data)

    dynamic_system_prompt = build_followup_system_prompt(
        base_persona_dict=request.persona_data,
        slider_settings=persona_sliders,
        script=request.script,
        followup_instruction=request.message,
    )

    messages_for_llm = sanitize_messages_script(
        system_msg=dynamic_system_prompt,
        history=request.history,
        user_text="(Silence prolongé de l'utilisateur...)",
        couples_to_keep=5,
    )

    try:
        stop = None

        if settings.SINHOME_LLM_BACKEND.lower() == "grok":
            response_text = await get_grok_response(
                messages_for_llm,
                temperature=0.8,
                top_p=0.9,
                max_tokens=128,
                stop=stop,
            )
        else:
            response_text = await vllm_client.get_vllm_response(
                messages_for_llm,
                temperature=0.8,
                top_p=0.9,
                max_tokens=128,
                stop=stop,
            )

        response_text = _dedupe_repeated_response(response_text)
        response_text = _strip_trailing_breaks(response_text)

        if _looks_like_refusal(response_text):
            refusal_msgs = [
                {
                    "role": "system",
                    "content": (
                        "Tu es une créatrice OnlyFans. Écris une relance courte et excitante. "
                        "Ne mentionne pas de refus, pas de règles, pas de meta, pas 'je suis une IA'. "
                        "Si la consigne est interdite, propose une relance alternative autorisée (adulte, consentie)."
                    ),
                },
                {"role": "user", "content": str(request.message)},
            ]
            if settings.SINHOME_LLM_BACKEND.lower() == "grok":
                response_text = await get_grok_response(
                    refusal_msgs,
                    temperature=0.8,
                    top_p=0.9,
                    max_tokens=150,
                    stop=stop,
                )
            else:
                response_text = await vllm_client.get_vllm_response(
                    refusal_msgs,
                    temperature=0.8,
                    top_p=0.9,
                    max_tokens=150,
                    stop=stop,
                )

            response_text = _dedupe_repeated_response(response_text)
            response_text = _strip_trailing_breaks(response_text)

        if isinstance(response_text, str) and len(response_text) > 500:
            rewrite_msgs = [
                {
                    "role": "system",
                    "content": "Réécris le texte suivant en 1-3 phrases MAX, même intensité, pas d'explication, pas de meta, pas de récit de vie. Réponds uniquement avec le message final.",
                },
                {"role": "user", "content": response_text},
            ]
            if settings.SINHOME_LLM_BACKEND.lower() == "grok":
                response_text = await get_grok_response(
                    rewrite_msgs,
                    temperature=0.8,
                    top_p=0.9,
                    max_tokens=192,
                    stop=stop,
                )
            else:
                response_text = await vllm_client.get_vllm_response(
                    rewrite_msgs,
                    temperature=0.8,
                    top_p=0.9,
                    max_tokens=192,
                    stop=stop,
                )

            response_text = _dedupe_repeated_response(response_text)
            response_text = _strip_trailing_breaks(response_text)

        logger.info("[script_followup] response (%d chars): %s...", len(response_text), str(response_text)[:100])

        asyncio.create_task(
            log_conversation(
                endpoint="/script_followup",
                system_prompt=dynamic_system_prompt.get("content", ""),
                history=request.history,
                user_message=f"[RELANCE] {request.message}",
                ai_response=response_text,
                session_id=request.session_id,
                raw_payload={
                    "session_id": request.session_id,
                    "message": request.message,
                    "history": request.history,
                    "persona_data": request.persona_data,
                    "script": request.script,
                },
            )
        )

        return ChatResponse(response=response_text)
    except httpx.ConnectError as e:
        logger.error("[script_followup] LLM connection failed: %s", e)
        asyncio.create_task(log_error("/script_followup", str(e), session_id=request.session_id))
        raise HTTPException(status_code=503, detail=f"Service LLM indisponible: {e}")
    except Exception as e:
        logger.exception("[script_followup] internal error")
        asyncio.create_task(log_error("/script_followup", str(e), session_id=request.session_id))
        raise HTTPException(status_code=500, detail=f"Erreur interne: {e}")
