import asyncio
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import List, Dict, Any, Optional
import httpx

from ..services import vllm_client
from ..services.script_unpersona_builder import build_script_paywall_prompt
from ..services.unpersona_builder import FALLBACK_NAME
from ..services.conversation_logger import log_conversation, log_error
from ..services.chat.sanitize import sanitize_messages_script
from ..services.chat.text_utils import (
    _dedupe_repeated_response,
    _looks_like_refusal,
    _strip_trailing_breaks,
)

paywall_router = APIRouter()

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

REQUIRED_SLIDERS = [
    "dominance",
    "audacity",
    "sales_tactic",
    "tone",
    "emotion",
    "initiative",
    "vocabulary",
    "emojis",
    "imperfection",
]


def _validate_sliders(v: Dict[str, Any]) -> Dict[str, Any]:
    missing = [s for s in REQUIRED_SLIDERS if s not in v]
    if missing:
        raise ValueError(f"persona_data manque les sliders: {missing}")
    return v


class ChatResponse(BaseModel):
    response: str


class ScriptPaywallRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    session_id: Optional[str] = None
    message: str
    history: List[Dict[str, Any]] = Field(default_factory=list)
    persona_data: Dict[str, Any]
    script: str = Field(..., min_length=1, description="Directive du scenario")
    media: List[str] = Field(
        default_factory=list,
        description="Descriptions des médias (photo/video) que la creatrice envoie",
    )
    price: float = Field(..., ge=0, description="Prix (ex: 15.0)")

    @field_validator("persona_data")
    @classmethod
    def validate_persona_data(cls, v):
        return _validate_sliders(v)


@paywall_router.post(
    "/script_paywall",
    response_model=ChatResponse,
    summary="Chat avec personnalité + directive de scénario + media + paywall",
)
async def script_paywall(request: ScriptPaywallRequest):
    logger.info(
        "[script_paywall] message: %s | script: %s | media_count: %s | price: %s",
        request.message[:50],
        request.script[:50],
        len(request.media or []),
        request.price,
    )

    persona_for_unpersona = dict(request.persona_data or {})
    persona_for_unpersona["name"] = FALLBACK_NAME
    dynamic_system_prompt = build_script_paywall_prompt(
        persona_dict=persona_for_unpersona,
        script=request.script,
        media=request.media,
        price=request.price,
    )

    messages_for_llm = sanitize_messages_script(
        system_msg=dynamic_system_prompt,
        history=request.history,
        user_text=request.message,
        couples_to_keep=5,
    )

    try:
        stop = None

        response_text = await vllm_client.get_vllm_response(
            messages_for_llm,
            temperature=0.65,
            top_p=0.9,
            max_tokens=512,
            stop=stop,
        )

        response_text = _dedupe_repeated_response(response_text)
        response_text = _strip_trailing_breaks(response_text)

        if _looks_like_refusal(response_text):
            response_text = await vllm_client.get_vllm_response(
                [
                    {
                        "role": "system",
                        "content": (
                            "Tu es une créatrice OnlyFans. Écris un message de chat court et excitant qui accompagne un média "
                            "et propose un accès payant (prix fourni). "
                            "Interdiction de mentionner un refus, des règles, ou que tu es une IA. "
                            "Pas de préambule, pas d'explication."
                        ),
                    },
                    {"role": "user", "content": str(request.message)},
                ],
                temperature=0.8,
                top_p=0.9,
                max_tokens=150,
                stop=stop,
            )

            response_text = _dedupe_repeated_response(response_text)
            response_text = _strip_trailing_breaks(response_text)

        logger.info("[script_paywall] response (%d chars): %s...", len(response_text), str(response_text)[:100])

        asyncio.create_task(
            log_conversation(
                endpoint="/script_paywall",
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
                    "media": request.media,
                    "price": request.price,
                },
            )
        )

        return ChatResponse(response=response_text)
    except httpx.ConnectError as e:
        logger.error("[script_paywall] LLM connection failed: %s", e)
        asyncio.create_task(log_error("/script_paywall", str(e), session_id=request.session_id))
        raise HTTPException(status_code=503, detail=f"Service LLM indisponible: {e}")
    except Exception as e:
        logger.exception("[script_paywall] internal error")
        asyncio.create_task(log_error("/script_paywall", str(e), session_id=request.session_id))
        raise HTTPException(status_code=500, detail=f"Erreur interne: {e}")
