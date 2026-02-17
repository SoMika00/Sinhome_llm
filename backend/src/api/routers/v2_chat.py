"""
V2 Chat Router - Endpoint avance avec prompt compact optimise.
Contrat Phase 4 : Personnalisation comportementale de l'IA.
Tous les endpoints sont non-bloquants : erreur = 503/500, jamais de crash serveur.
Token budget reduit pour eviter de noyer le modele.
"""
import asyncio
import logging
import traceback
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from ..config import settings
from ..services import vllm_client
from ..services.conversation_logger import log_conversation, log_error
from ..services.grok_client import get_grok_response
from ..services.v2_persona_builder import (
    V2PersonaSettings,
    build_v2_system_prompt,
    build_v2_script_prompt,
    build_v2_followup_prompt,
)
from ..services.chat.retry import _get_vllm_response_with_dup_retry
from ..services.chat.sanitize import sanitize_messages_limited, sanitize_messages_script
from ..services.chat.schemas import ChatResponse
from ..services.chat.text_utils import (
    _dedupe_repeated_response,
    _looks_like_refusal,
    _strip_trailing_breaks,
)

v2_router = APIRouter(prefix="/v2", tags=["V2 Chat"])

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

# ── Budget tokens V2 (optimise vs V1) ───────────────────────────────
# Prompt systeme V2 ~ 600 tokens (vs 1500 en V1)
# On garde plus de place pour l'historique et la reponse
V2_TOKEN_BUDGET = 2800      # tokens max pour historique (systeme exclu)
V2_COUPLES_TO_KEEP = 10     # max 10 echanges user/assistant recents
V2_MAX_TOKENS = 200         # reponse max (1-2 phrases = ~60-100 tokens)
V2_SCRIPT_COUPLES = 5       # moins d'historique en mode script
V2_FOLLOWUP_COUPLES = 4     # encore moins pour relance

REQUIRED_SLIDERS = [
    "dominance", "audacity", "sales_tactic", "tone",
    "emotion", "initiative", "vocabulary", "emojis", "imperfection",
]


def _validate_sliders(v: Dict[str, Any]) -> Dict[str, Any]:
    missing = [s for s in REQUIRED_SLIDERS if s not in v]
    if missing:
        raise ValueError(f"persona_data manque les sliders: {missing}")
    return v


def _as_int(x: Any, default: int) -> int:
    try:
        v = int(x)
        return v if 1 <= v <= 5 else default
    except (ValueError, TypeError):
        return default


def _persona_from_dict(d: Dict[str, Any]) -> V2PersonaSettings:
    return V2PersonaSettings(
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


def _safe_log(endpoint, system_prompt, history, user_message, ai_response, session_id, raw_payload):
    """Log fire-and-forget. Ne bloque JAMAIS."""
    try:
        asyncio.create_task(log_conversation(
            endpoint=endpoint,
            system_prompt=system_prompt.get("content", "") if isinstance(system_prompt, dict) else str(system_prompt),
            history=history, user_message=user_message, ai_response=ai_response,
            session_id=session_id, raw_payload=raw_payload,
        ))
    except Exception:
        pass


def _safe_log_error(endpoint, error, session_id):
    """Log erreur fire-and-forget."""
    try:
        asyncio.create_task(log_error(endpoint, str(error)[:500], session_id=session_id))
    except Exception:
        pass


def _clean(text):
    """Nettoyage texte non-bloquant."""
    try:
        text = _dedupe_repeated_response(text)
        text = _strip_trailing_breaks(text)
    except Exception:
        pass
    return text


async def _safe_llm_call(messages, temperature=0.65, max_tokens=V2_MAX_TOKENS, stop=None, use_grok=False):
    """Appel LLM avec gestion d'erreur. Retourne texte ou leve une exception."""
    if use_grok:
        return await get_grok_response(messages, temperature=temperature, top_p=0.9, max_tokens=max_tokens, stop=stop)
    else:
        return await vllm_client.get_vllm_response(messages, temperature=temperature, top_p=0.9, max_tokens=max_tokens, stop=stop)


async def _refusal_retry(message, name="Seline", use_grok=False, max_tokens=V2_MAX_TOKENS):
    """Retry anti-refus. Retourne le texte de remplacement."""
    msgs = [
        {"role": "system", "content": f"Tu es {name} (OnlyFans). Reponse sexy, sans refus, sans IA. 1-2 phrases."},
        {"role": "user", "content": str(message)},
    ]
    rt = await _safe_llm_call(msgs, temperature=0.85, max_tokens=max_tokens, use_grok=use_grok)
    return _clean(rt)


async def _shorten_if_long(text, max_len=400, use_grok=False):
    """Raccourcit si trop long. Non-bloquant si echec."""
    if not isinstance(text, str) or len(text) <= max_len:
        return text
    try:
        msgs = [
            {"role": "system", "content": "Reecris en 1-2 phrases MAX. Meme intensite et style. Message final uniquement."},
            {"role": "user", "content": text},
        ]
        rt = await _safe_llm_call(msgs, temperature=0.8, max_tokens=V2_MAX_TOKENS, use_grok=use_grok)
        return _clean(rt)
    except Exception:
        # Fallback: tronquer manuellement au dernier point/espace
        cut = text[:max_len]
        last_dot = max(cut.rfind('.'), cut.rfind('!'), cut.rfind('?'), cut.rfind('\n'))
        if last_dot > max_len // 2:
            return cut[:last_dot + 1]
        return cut


class V2PersonalityChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str
    history: List[Dict[str, Any]] = Field(default_factory=list)
    persona_data: Dict[str, Any]

    @field_validator("persona_data")
    @classmethod
    def validate_persona_data(cls, v):
        return _validate_sliders(v)


class V2ScriptChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str
    history: List[Dict[str, Any]] = Field(default_factory=list)
    persona_data: Dict[str, Any]
    script: str = Field(..., min_length=1)

    @field_validator("persona_data")
    @classmethod
    def validate_persona_data(cls, v):
        return _validate_sliders(v)


@v2_router.post("/personality_chat", response_model=ChatResponse, summary="V2 - Chat avec personnalite avancee")
async def v2_personality_chat(request: V2PersonalityChatRequest):
    use_grok = settings.SINHOME_LLM_BACKEND.lower() == "grok"
    pname = (request.persona_data or {}).get("name") or "Seline"
    logger.info("[v2/personality_chat] user=%s grok=%s", request.message[:80], use_grok)

    try:
        persona_sliders = _persona_from_dict(request.persona_data)
        dynamic_system_prompt = build_v2_system_prompt(
            base_persona_dict=request.persona_data, slider_settings=persona_sliders,
        )

        if use_grok:
            messages_for_llm, _ = sanitize_messages_limited(
                system_msg=dynamic_system_prompt, history=request.history,
                user_text=request.message,
                couples_to_keep=V2_COUPLES_TO_KEEP, token_budget=V2_TOKEN_BUDGET,
            )
            response_text = await _safe_llm_call(messages_for_llm, use_grok=True)
        else:
            response_text, meta = await _get_vllm_response_with_dup_retry(
                base_system_prompt=dynamic_system_prompt,
                history=request.history, user_text=request.message,
                stop=None, temperature=0.65, top_p=0.9,
                max_tokens=V2_MAX_TOKENS, max_dup_reprompts=3,
            )

        response_text = _clean(response_text)

        # Retry si refus
        if _looks_like_refusal(response_text):
            logger.warning("[v2/personality_chat] refusal detected, retrying")
            response_text = await _refusal_retry(request.message, name=pname, use_grok=use_grok)

        # Raccourcir si trop long
        response_text = await _shorten_if_long(response_text, use_grok=use_grok)

        logger.info("[v2/personality_chat] OK (%d chars)", len(response_text))
        _safe_log("/v2/personality_chat", dynamic_system_prompt, request.history,
            request.message, response_text, request.session_id,
            {"prompt_version": "v2", "backend": "grok" if use_grok else "vllm"})
        return ChatResponse(response=response_text)

    except httpx.ConnectError as e:
        _safe_log_error("/v2/personality_chat", e, request.session_id)
        raise HTTPException(status_code=503, detail=f"LLM indisponible: {e}")
    except Exception as e:
        logger.error("[v2/personality_chat] %s", traceback.format_exc())
        _safe_log_error("/v2/personality_chat", e, request.session_id)
        raise HTTPException(status_code=500, detail=f"Erreur interne: {str(e)[:200]}")


@v2_router.post("/script_chat", response_model=ChatResponse, summary="V2 - Chat avec personnalite + scenario")
async def v2_script_chat(request: V2ScriptChatRequest):
    use_grok = settings.SINHOME_LLM_BACKEND.lower() == "grok"
    logger.info("[v2/script_chat] msg=%s script=%s", request.message[:50], request.script[:50])

    try:
        persona_sliders = _persona_from_dict(request.persona_data)
        dynamic_system_prompt = build_v2_script_prompt(
            base_persona_dict=request.persona_data, slider_settings=persona_sliders,
            script=request.script,
        )
        messages_for_llm = sanitize_messages_script(
            system_msg=dynamic_system_prompt, history=request.history,
            user_text=request.message, couples_to_keep=V2_SCRIPT_COUPLES,
        )
        stop = ["\nuser:", "\nassistant:", "\nUser:", "\nAssistant:"]
        response_text = await _safe_llm_call(
            messages_for_llm, temperature=0.8, max_tokens=150,
            stop=stop, use_grok=use_grok,
        )
        response_text = _clean(response_text)

        if _looks_like_refusal(response_text):
            response_text = await _refusal_retry(request.message, use_grok=use_grok, max_tokens=150)

        response_text = await _shorten_if_long(response_text, use_grok=use_grok)

        _safe_log("/v2/script_chat", dynamic_system_prompt, request.history,
            request.message, response_text, request.session_id,
            {"prompt_version": "v2", "script": request.script[:100]})
        return ChatResponse(response=response_text)

    except httpx.ConnectError as e:
        _safe_log_error("/v2/script_chat", e, request.session_id)
        raise HTTPException(status_code=503, detail=f"LLM indisponible: {e}")
    except Exception as e:
        logger.error("[v2/script_chat] %s", traceback.format_exc())
        _safe_log_error("/v2/script_chat", e, request.session_id)
        raise HTTPException(status_code=500, detail=f"Erreur interne: {str(e)[:200]}")


@v2_router.post("/script_followup", response_model=ChatResponse, summary="V2 - Relance avec personnalite avancee")
async def v2_script_followup(request: V2ScriptChatRequest):
    use_grok = settings.SINHOME_LLM_BACKEND.lower() == "grok"
    logger.info("[v2/script_followup] msg=%s script=%s", request.message[:50], request.script[:50])

    try:
        persona_sliders = _persona_from_dict(request.persona_data)
        dynamic_system_prompt = build_v2_followup_prompt(
            base_persona_dict=request.persona_data, slider_settings=persona_sliders,
            script=request.script, followup_instruction=request.message,
        )
        messages_for_llm = sanitize_messages_script(
            system_msg=dynamic_system_prompt, history=request.history,
            user_text="(Silence prolonge de l'utilisateur...)",
            couples_to_keep=V2_FOLLOWUP_COUPLES,
        )
        response_text = await _safe_llm_call(
            messages_for_llm, temperature=0.8, max_tokens=128, use_grok=use_grok,
        )
        response_text = _clean(response_text)

        if _looks_like_refusal(response_text):
            response_text = await _refusal_retry(request.message, use_grok=use_grok, max_tokens=128)

        response_text = await _shorten_if_long(response_text, max_len=300, use_grok=use_grok)

        _safe_log("/v2/script_followup", dynamic_system_prompt, request.history,
            f"[RELANCE] {request.message}", response_text, request.session_id,
            {"prompt_version": "v2", "script": request.script[:100]})
        return ChatResponse(response=response_text)

    except httpx.ConnectError as e:
        _safe_log_error("/v2/script_followup", e, request.session_id)
        raise HTTPException(status_code=503, detail=f"LLM indisponible: {e}")
    except Exception as e:
        logger.error("[v2/script_followup] %s", traceback.format_exc())
        _safe_log_error("/v2/script_followup", e, request.session_id)
        raise HTTPException(status_code=500, detail=f"Erreur interne: {str(e)[:200]}")
