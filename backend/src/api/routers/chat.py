# backend/src/api/routers/chat.py

import asyncio
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from typing import List, Dict, Any, Optional
import httpx
import re

from ..services import vllm_client
from ..config import settings
from ..services.persona_builder import (
    PersonaSettings, 
    build_dynamic_system_prompt,
    build_followup_system_prompt,
    FALLBACK_PERSONALITY_DATA
)
from ..services.script_persona_builder import build_script_chat_system_prompt
from ..services.conversation_logger import log_conversation, log_error

ext_router = APIRouter()

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

# --- Schemas ---
REQUIRED_SLIDERS = ['dominance', 'audacity', 'sales_tactic', 'tone', 'emotion', 'initiative', 'vocabulary', 'emojis', 'imperfection']

def _validate_sliders(v: Dict[str, Any]) -> Dict[str, Any]:
    """Validateur commun pour persona_data"""
    missing = [s for s in REQUIRED_SLIDERS if s not in v]
    if missing:
        raise ValueError(f"persona_data manque les sliders: {missing}")
    return v

class ChatResponse(BaseModel):
    response: str

class DirectChatRequest(BaseModel):
    """Payload pour /direct_chat - test simple sans config"""
    message: str

class PersonalityChatRequest(BaseModel):
    """Payload pour /personality_chat - requiert persona_data avec sliders"""
    session_id: Optional[str] = None
    message: str
    history: List[Dict[str, Any]] = Field(default_factory=list)
    persona_data: Dict[str, Any]
    
    @field_validator('persona_data')
    @classmethod
    def validate_persona_data(cls, v):
        return _validate_sliders(v)

class ScriptChatRequest(BaseModel):
    """Payload pour /script_chat - requiert persona_data + script"""
    session_id: Optional[str] = None
    message: str
    history: List[Dict[str, Any]] = Field(default_factory=list)
    persona_data: Dict[str, Any]
    script: str = Field(..., min_length=1, description="Directive du scenario")
    
    @field_validator('persona_data')
    @classmethod
    def validate_persona_data(cls, v):
        return _validate_sliders(v)


# --- Utils persona ---
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

# --- Sanitize chat messages ---
def _merge_content(c1: Any, c2: Any) -> Any:
    # Concatène intelligemment string <-> liste (multimodal)
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

def sanitize_messages(
    system_msg: Dict[str, Any] | None,
    history: List[Dict[str, Any]],
    user_text: Any,
) -> List[Dict[str, Any]]:
    msgs: List[Dict[str, Any]] = []

    if system_msg and system_msg.get("role") == "system":
        msgs.append({"role": "system", "content": system_msg.get("content", "")})

    # 2) historique: garder user/assistant, fusionner doublons consécutifs
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

    # 3) forcer dernier = user (et fusionner si déjà user)
    if collapsed and collapsed[-1]["role"] == "user":
        collapsed[-1]["content"] = _merge_content(collapsed[-1]["content"], user_text)
    else:
        collapsed.append({"role": "user", "content": user_text})

    msgs.extend(collapsed)
    return msgs


def _trim_history_last_couples(
    history: List[Dict[str, Any]],
    couples_to_keep: int,
) -> List[Dict[str, Any]]:
    """
    Pour /script_chat uniquement: garde les N derniers "couples" (échanges) sans
    modifier le contenu des messages.

    Règle de comptage:
    - Les messages consécutifs du même rôle forment un bloc (AA ou UU).
    - Un "couple" = 2 blocs consécutifs (ex: A U) ou (U A).
    - On garde les derniers N couples (donc jusqu'à 2N blocs).
    """
    if couples_to_keep <= 0:
        return []

    # 1) Filtrer les messages (sans fusion)
    filtered: List[Dict[str, Any]] = []
    for m in history:
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        content = m.get("content")
        if content is None or (isinstance(content, str) and not content.strip()):
            continue
        # /script_chat: ignorer le bruit assistant (ex: "🤣🤣")
        if role == "assistant" and _looks_like_only_emojis_or_punct(content):
            continue
        filtered.append({"role": role, "content": content})

    if not filtered:
        return []

    # 2) Grouper en blocs consécutifs (sans fusion)
    blocks: List[List[Dict[str, Any]]] = []
    for m in filtered:
        if not blocks or blocks[-1][0]["role"] != m["role"]:
            blocks.append([m])
        else:
            blocks[-1].append(m)

    # 3) Prendre les derniers N couples (2 blocs par couple)
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


def _looks_like_only_emojis_or_punct(x: Any) -> bool:
    if not isinstance(x, str):
        return False
    s = x.strip()
    if not s:
        return True
    # Si aucun caractère alphanumérique (lettre/chiffre), c'est du "bruit" (emojis/punct)
    return re.search(r"[A-Za-z0-9À-ÖØ-öø-ÿ]", s) is None


def sanitize_messages_script(
    system_msg: Dict[str, Any] | None,
    history: List[Dict[str, Any]],
    user_text: Any,
    couples_to_keep: int = 5,
) -> List[Dict[str, Any]]:
    """Sanitization spécifique /script_chat: trim par couples, sans collapse."""
    msgs: List[Dict[str, Any]] = []

    if system_msg and system_msg.get("role") == "system":
        msgs.append({"role": "system", "content": system_msg.get("content", "")})

    trimmed_history = _trim_history_last_couples(history, couples_to_keep)
    msgs.extend(trimmed_history)

    msgs.append({"role": "user", "content": user_text})
    return msgs


def sanitize_messages_script_midnight(
    system_msg: Dict[str, Any] | None,
    history: List[Dict[str, Any]],
    user_text: Any,
    couples_to_keep: int = 5,
) -> List[Dict[str, Any]]:
    msgs: List[Dict[str, Any]] = []

    if system_msg and system_msg.get("role") == "system":
        msgs.append({"role": "system", "content": system_msg.get("content", "")})

    trimmed_history = _trim_history_last_couples(history, couples_to_keep)

    normalized: List[Dict[str, Any]] = []
    for m in trimmed_history:
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        content = m.get("content")
        if content is None or (isinstance(content, str) and not content.strip()):
            continue
        if not normalized:
            if role != "user":
                continue
            normalized.append({"role": role, "content": content})
            continue
        if normalized[-1]["role"] == role:
            normalized[-1]["content"] = _merge_content(normalized[-1]["content"], content)
        else:
            normalized.append({"role": role, "content": content})

    if normalized and normalized[-1]["role"] == "user":
        normalized[-1]["content"] = _merge_content(normalized[-1]["content"], user_text)
    else:
        normalized.append({"role": "user", "content": user_text})

    msgs.extend(normalized)
    return msgs

# --- ENDPOINT /direct_chat (test simple) ---
@ext_router.post(
    "/direct_chat",
    response_model=ChatResponse,
    summary="Test direct - persona par defaut, pas d'historique",
)
async def direct_chat(request: DirectChatRequest):
    logger.info("[direct_chat] message: %s", request.message[:100])
    
    # Persona et sliders par defaut
    default_sliders = PersonaSettings()
    system_prompt = build_dynamic_system_prompt(
        base_persona_dict=FALLBACK_PERSONALITY_DATA,
        slider_settings=default_sliders,
    )
    
    messages_for_llm = [
        system_prompt,
        {"role": "user", "content": request.message}
    ]
    
    try:
        response_text = await vllm_client.get_vllm_response(messages_for_llm)
        logger.info("[direct_chat] response (%d chars): %s...", len(response_text), str(response_text)[:100])
        
        # Log de la conversation (fire-and-forget, zéro latence)
        asyncio.create_task(log_conversation(
            endpoint="/direct_chat",
            system_prompt=system_prompt.get("content", ""),
            history=[],
            user_message=request.message,
            ai_response=response_text,
            session_id=None,
            raw_payload={"message": request.message},
        ))
        
        return ChatResponse(response=response_text)
    except httpx.ConnectError as e:
        logger.error("[direct_chat] LLM connection failed: %s", e)
        asyncio.create_task(log_error("/direct_chat", str(e), context={"message": request.message[:200]}))
        raise HTTPException(status_code=503, detail=f"Service LLM indisponible: {e}")
    except Exception as e:
        logger.exception("[direct_chat] internal error")
        asyncio.create_task(log_error("/direct_chat", str(e), context={"message": request.message[:200]}))
        raise HTTPException(status_code=500, detail=f"Erreur interne: {e}")


# --- ENDPOINT /personality_chat ---
@ext_router.post(
    "/personality_chat",
    response_model=ChatResponse,
    summary="Chat avec personnalité configurable via sliders",
)
async def personality_chat(request: PersonalityChatRequest):
    logger.info("[personality_chat] message: %s", request.message[:100])

    persona_sliders = _persona_from_lambda_dict(request.persona_data)
    dynamic_system_prompt = build_dynamic_system_prompt(
        base_persona_dict=request.persona_data,
        slider_settings=persona_sliders,
    )

    messages_for_llm = sanitize_messages(
        system_msg=dynamic_system_prompt,
        history=request.history,
        user_text=request.message,
    )
    logger.debug("Messages LLM: %s", messages_for_llm)

    try:
        response_text = await vllm_client.get_vllm_response(messages_for_llm)
        logger.info("[personality_chat] response (%d chars): %s...", len(response_text), str(response_text)[:100])
        
        # Log de la conversation (fire-and-forget, zéro latence)
        asyncio.create_task(log_conversation(
            endpoint="/personality_chat",
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
            },
        ))
        
        return ChatResponse(response=response_text)
    except httpx.ConnectError as e:
        logger.error("[personality_chat] LLM connection failed: %s", e)
        asyncio.create_task(log_error("/personality_chat", str(e), session_id=request.session_id))
        raise HTTPException(status_code=503, detail=f"Service LLM indisponible: {e}")
    except Exception as e:
        logger.exception("[personality_chat] internal error")
        asyncio.create_task(log_error("/personality_chat", str(e), session_id=request.session_id))
        raise HTTPException(status_code=500, detail=f"Erreur interne: {e}")


# --- ENDPOINT /script_chat ---
@ext_router.post(
    "/script_chat",
    response_model=ChatResponse,
    summary="Chat avec personnalité + directive de scénario",
)
async def script_chat(request: ScriptChatRequest):
    logger.info("[script_chat] message: %s | script: %s", 
                request.message[:50], request.script[:50])

    persona_sliders = _persona_from_lambda_dict(request.persona_data)
    
    # Construction du prompt avec le script additionnel
    dynamic_system_prompt = build_script_chat_system_prompt(
        base_persona_dict=request.persona_data,
        slider_settings=persona_sliders,
        script=request.script,
    )

    if "midnight" in settings.VLLM_MODEL_NAME.lower():
        messages_for_llm = sanitize_messages_script_midnight(
            system_msg=dynamic_system_prompt,
            history=request.history,
            user_text=request.message,
            couples_to_keep=5,
        )
    else:
        messages_for_llm = sanitize_messages_script(
            system_msg=dynamic_system_prompt,
            history=request.history,
            user_text=request.message,
            couples_to_keep=5,
        )
    logger.debug("Messages LLM (avec script): %s", messages_for_llm)

    try:
        response_text = await vllm_client.get_vllm_response(
            messages_for_llm,
            temperature=0.65,
            top_p=0.9,
            max_tokens=512,
        )
        logger.info("[script_chat] response (%d chars): %s...", len(response_text), str(response_text)[:100])
        
        # Log de la conversation (fire-and-forget, zéro latence)
        asyncio.create_task(log_conversation(
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
        ))
        
        return ChatResponse(response=response_text)
    except httpx.ConnectError as e:
        logger.error("[script_chat] LLM connection failed: %s", e)
        asyncio.create_task(log_error("/script_chat", str(e), session_id=request.session_id))
        raise HTTPException(status_code=503, detail=f"Service LLM indisponible: {e}")
    except Exception as e:
        logger.exception("[script_chat] internal error")
        asyncio.create_task(log_error("/script_chat", str(e), session_id=request.session_id))
        raise HTTPException(status_code=500, detail=f"Erreur interne: {e}")


# --- ENDPOINT /script_followup ---
# Endpoint de RELANCE : l'utilisateur n'a pas répondu, on doit recapter son attention.
# MÊME PAYLOAD que /script_chat, mais `message` = la consigne de follow up.
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
    # message = la consigne de follow up (ex: "Envoie un message taquin pour reprendre contact")
    logger.info("[script_followup] followup_instruction (message): %s | script: %s",
                request.message[:50], request.script[:50])

    persona_sliders = _persona_from_lambda_dict(request.persona_data)

    # Prompt spécial RELANCE : inclut le contexte "l'user n'a pas répondu" + la consigne
    dynamic_system_prompt = build_followup_system_prompt(
        base_persona_dict=request.persona_data,
        slider_settings=persona_sliders,
        script=request.script,
        followup_instruction=request.message,  # message = consigne de followup
    )

    # On utilise un marqueur spécial de silence au lieu de "[RELANCE]"
    # pour que le modèle comprenne qu'il doit agir sur le silence.
    if "midnight" in settings.VLLM_MODEL_NAME.lower():
        messages_for_llm = sanitize_messages_script_midnight(
            system_msg=dynamic_system_prompt,
            history=request.history,
            user_text="(Silence prolongé de l'utilisateur...)",
            couples_to_keep=5,
        )
    else:
        messages_for_llm = sanitize_messages_script(
            system_msg=dynamic_system_prompt,
            history=request.history,
            user_text="(Silence prolongé de l'utilisateur...)",
            couples_to_keep=5,
        )
    logger.debug("Messages LLM (followup): %s", messages_for_llm)

    try:
        response_text = await vllm_client.get_vllm_response(
            messages_for_llm,
            temperature=0.65,
            top_p=0.9,
            max_tokens=128,
        )
        logger.info("[script_followup] response (%d chars): %s...", len(response_text), str(response_text)[:100])
        
        # Log de la conversation (fire-and-forget, zéro latence)
        asyncio.create_task(log_conversation(
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
        ))
        
        return ChatResponse(response=response_text)
    except httpx.ConnectError as e:
        logger.error("[script_followup] LLM connection failed: %s", e)
        asyncio.create_task(log_error("/script_followup", str(e), session_id=request.session_id))
        raise HTTPException(status_code=503, detail=f"Service LLM indisponible: {e}")
    except Exception as e:
        logger.exception("[script_followup] internal error")
        asyncio.create_task(log_error("/script_followup", str(e), session_id=request.session_id))
        raise HTTPException(status_code=500, detail=f"Erreur interne: {e}")
