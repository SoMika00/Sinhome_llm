# backend/src/api/routers/chat.py  (REMPLACER COMPLÈTEMENT)

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import httpx

from ..services import vllm_client
from ..services.persona_builder import PersonaSettings, build_dynamic_system_prompt

router = APIRouter()
ext_router = APIRouter()  # compat Lambda

# --- Logging ---
logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

# --- Schemas ---
class ConfiguredChatRequest(BaseModel):
    message: str = Field(...)
    history: List[Dict[str, Any]] = Field(default_factory=list)
    persona: PersonaSettings = Field(...)

class ChatResponse(BaseModel):
    response: str

class LambdaChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str
    history: List[Dict[str, Any]] = Field(default_factory=list)
    persona_data: Dict[str, Any] = Field(default_factory=dict)

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

    # 1) system en tête si fourni
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

# --- ENDPOINT LAMBDA (prod) ---
@ext_router.post(
    "/personality_chat",
    response_model=ChatResponse,
    summary="Endpoint principal pour la Lambda, 100% stateless",
)
async def personality_chat_compat(request: LambdaChatRequest):
    logger.info("📥 Payload reçu /personality_chat: %s", request.dict())

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
    logger.debug("📤 Messages envoyés au LLM (sanitized): %s", messages_for_llm)

    try:
        response_text = await vllm_client.get_vllm_response(messages_for_llm)
        logger.info("✅ Réponse LLM: %s", str(response_text)[:200])
        return ChatResponse(response=response_text)
    except httpx.ConnectError as e:
        logger.error("❌ Impossible de contacter le service LLM: %s", e)
        raise HTTPException(status_code=503, detail=f"Impossible de contacter le service LLM: {e}")
    except Exception as e:
        logger.exception("❌ Erreur interne lors de l'appel au LLM")
        raise HTTPException(status_code=500, detail=f"Erreur interne lors de l'appel au LLM: {e}")

# --- ENDPOINT TEST (ancien frontend) ---
@router.post(
    "/configured",
    response_model=ChatResponse,
    summary="Générer une réponse pour les tests (fallback persona)",
)
async def handle_configured_chat(request: ConfiguredChatRequest):
    logger.info("📥 Payload reçu /configured: %s", request.dict())

    dynamic_system_prompt = build_dynamic_system_prompt(
        base_persona_dict={},
        slider_settings=request.persona,
    )

    messages_for_llm = sanitize_messages(
        system_msg=dynamic_system_prompt,
        history=request.history,
        user_text=request.message,
    )
    logger.debug("📤 Messages envoyés au LLM (sanitized): %s", messages_for_llm)

    try:
        response_text = await vllm_client.get_vllm_response(messages_for_llm)
        logger.info("✅ Réponse LLM: %s", str(response_text)[:200])
        return ChatResponse(response=response_text)
    except Exception as e:
        logger.exception("❌ Erreur interne")
        raise HTTPException(status_code=500, detail=f"Erreur interne: {e}")
