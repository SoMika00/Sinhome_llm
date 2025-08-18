
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from uuid import UUID
from types import SimpleNamespace
import httpx

from ..connectors import db
from ..services import vllm_client
from ..services.persona_builder import (
    PersonaSettings,
    build_dynamic_system_prompt,
)


router = APIRouter()

# --- Modèles de requête/réponse (endpoints historiques) ---

class SimpleChatRequest(BaseModel):
    message: str = Field(...)
    history: List[Dict[str, str]] = Field(default_factory=list)

class ConfiguredChatRequest(BaseModel):
    message: str = Field(...)
    history: List[Dict[str, str]] = Field(default_factory=list)
    persona: PersonaSettings = Field(...)

class ChatResponse(BaseModel):
    response: str


# --- Outils communs ---

def _fallback_personality() -> Any:
    """
    Personnalité de repli si la BDD est indisponible / vide.
    build_dynamic_system_prompt utilise hasattr => SimpleNamespace suffit.
    """
    return SimpleNamespace(
        id=None,
        name="Seline",
        base_prompt=(
            "Tu es une assistante de chat utile, claire et respectueuse. "
            "Évite les sujets interdits et garde un ton professionnel."
        ),
        age=None,
        gender=None,
        race=None,
        eye_color=None,
        hair_color=None,
        hair_type=None,
        personality_tone="équilibré",
        personality_humor=None,
        personality_favorite_expressions=[],
        preferences_interests=[],
        preferences_forbidden_topics=[],
        preferences_emoji_usage=None,
        interactions_message_style=None,
    )


# --- Endpoint avancé (historique) : utilise la BDD + sliders fournis par le client ---
@router.post(
    "/configured",
    response_model=ChatResponse,
    summary="Générer une réponse avec une personnalité dynamique (BDD + sliders)"
)
async def handle_configured_chat(request: ConfiguredChatRequest):
    """
    Utilise une personnalité 'cible' en BDD + modulations via sliders.
    """
    TARGET_MODEL_ID = UUID("f0d654d4-96ca-4c50-af9d-5fa7009c9b67")

    try:
        base_personality = await db.get_model_by_id(TARGET_MODEL_ID)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Erreur BDD lors de la récupération du modèle: {e}"
        )

    if not base_personality:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Le modèle avec l'ID {TARGET_MODEL_ID} est introuvable."
        )

    dynamic_system_prompt = build_dynamic_system_prompt(
        base_personality=base_personality,
        slider_settings=request.persona
    )

    messages_for_llm = [dynamic_system_prompt] + request.history + [
        {"role": "user", "content": request.message}
    ]

    try:
        response_text = await vllm_client.get_vllm_response(messages_for_llm)
        return ChatResponse(response=response_text)
    except httpx.ConnectError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Impossible de se connecter au service LLM: {e}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur interne: {e}"
        )


@router.post(
    "/",
    response_model=ChatResponse,
    summary="Générer une réponse de chat simple (fallback sans BDD)"
)
async def handle_simple_chat(request: SimpleChatRequest):
    base_personality = _fallback_personality()
    default_persona = PersonaSettings()
    dynamic_system_prompt = build_dynamic_system_prompt(
        base_personality=base_personality,
        slider_settings=default_persona
    )

    messages_for_llm = [dynamic_system_prompt] + request.history + [
        {"role": "user", "content": request.message}
    ]

    response_text = await vllm_client.get_vllm_response(messages_for_llm)
    return ChatResponse(response=response_text)



ext_router = APIRouter()

class LambdaChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str
    history: List[Dict[str, str]] = Field(default_factory=list)
    persona_data: Dict[str, Any] = Field(default_factory=dict)

def _as_int(x: Any, default: int) -> int:
    try:
        v = int(x)
        return v if 1 <= v <= 5 else default
    except Exception:
        return default

def _persona_from_lambda_dict(d: Dict[str, Any]) -> PersonaSettings:
    return PersonaSettings(
        sales_tactic=_as_int(d.get("sales_tactic", 2), 2),
        dominance=_as_int(d.get("dominance", 3), 3),
        audacity=_as_int(d.get("audacity", 3), 3),
        tone=_as_int(d.get("tone", 2), 2),
        emotion=_as_int(d.get("emotion", 3), 3),
        initiative=_as_int(d.get("initiative", 3), 3),
        vocabulary=_as_int(d.get("vocabulary", 3), 3),
        emojis=_as_int(d.get("emojis", 3), 3),
        imperfection=_as_int(d.get("imperfection", 1), 1),
    )

@ext_router.post(
    "/personality_chat",
    response_model=ChatResponse,
    summary="Compatibilité Lambda: {session_id, message, history, persona_data}"
)
async def personality_chat_compat(request: LambdaChatRequest):
    """
    Route de compatibilité pour la Lambda (aucune modif Lambda requise).
    - Essaie d'utiliser la personnalité BDD (ID fixe). En cas d'échec -> fallback.
    - Mappe persona_data -> PersonaSettings.
    """
    TARGET_MODEL_ID = UUID("f0d654d4-96ca-4c50-af9d-5fa7009c9b67")

    # Personnalité: DB ou fallback
    base_personality = None
    try:
        base_personality = await db.get_model_by_id(TARGET_MODEL_ID)
    except Exception:
        base_personality = None
    if not base_personality:
        base_personality = _fallback_personality()

    persona = _persona_from_lambda_dict(request.persona_data)

    dynamic_system_prompt = build_dynamic_system_prompt(
        base_personality=base_personality,
        slider_settings=persona
    )

    messages_for_llm = [dynamic_system_prompt] + request.history + [
        {"role": "user", "content": request.message}
    ]

    try:
        response_text = await vllm_client.get_vllm_response(messages_for_llm)
        return ChatResponse(response=response_text)
    except httpx.ConnectError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Impossible de se connecter au service LLM: {e}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur interne: {e}"
        )
