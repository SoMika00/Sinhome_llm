# Fichier: backend/src/api/routers/chat.py (REMPLACER COMPLÈTEMENT)

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import httpx

from ..services import vllm_client
from ..services.persona_builder import PersonaSettings, build_dynamic_system_prompt

router = APIRouter()
ext_router = APIRouter() # Pour la compatibilité Lambda

# --- Modèles Pydantic ---
class ConfiguredChatRequest(BaseModel):
    message: str = Field(...)
    history: List[Dict[str, str]] = Field(default_factory=list)
    persona: PersonaSettings = Field(...)

class ChatResponse(BaseModel):
    response: str

class LambdaChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str
    history: List[Dict[str, str]] = Field(default_factory=list)
    # C'est ici que la Lambda envoie toutes les infos de la personnalité
    persona_data: Dict[str, Any] = Field(default_factory=dict)

# Fonctions utilitaires pour convertir le dict de la Lambda en objet PersonaSettings
def _as_int(x: Any, default: int) -> int:
    try: v = int(x); return v if 1 <= v <= 5 else default
    except (ValueError, TypeError): return default

def _persona_from_lambda_dict(d: Dict[str, Any]) -> PersonaSettings:
    return PersonaSettings(
        sales_tactic=_as_int(d.get("sales_tactic"), 2), dominance=_as_int(d.get("dominance"), 3),
        audacity=_as_int(d.get("audacity"), 3), tone=_as_int(d.get("tone"), 2),
        emotion=_as_int(d.get("emotion"), 3), initiative=_as_int(d.get("initiative"), 3),
        vocabulary=_as_int(d.get("vocabulary"), 3), emojis=_as_int(d.get("emojis"), 3),
        imperfection=_as_int(d.get("imperfection"), 1),
    )

# --- ENDPOINT LAMBDA : /personality_chat (Endpoint de Production) ---
@ext_router.post(
    "/personality_chat",
    response_model=ChatResponse,
    summary="Endpoint principal pour la Lambda, 100% stateless"
)
async def personality_chat_compat(request: LambdaChatRequest):
    """
    Route de production appelée par la Lambda.
    Elle récupère la personnalité de base et les réglages des sliders depuis la payload.
    Aucun appel à une base de données n'est fait ici.
    """
    # 1. On extrait les réglages des sliders du dictionnaire `persona_data`
    persona_sliders = _persona_from_lambda_dict(request.persona_data)
    
    # 2. On passe le dictionnaire `persona_data` entier comme personnalité de base
    dynamic_system_prompt = build_dynamic_system_prompt(
        base_persona_dict=request.persona_data,
        slider_settings=persona_sliders
    )
    
    messages_for_llm = [dynamic_system_prompt] + request.history + [
        {"role": "user", "content": request.message}
    ]

    try:
        response_text = await vllm_client.get_vllm_response(messages_for_llm)
        return ChatResponse(response=response_text)
    except httpx.ConnectError as e:
        raise HTTPException(status_code=503, detail=f"Impossible de contacter le service LLM: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur interne lors de l'appel au LLM: {e}")


# --- ENDPOINT POUR LES TESTS (Ancien Frontend) ---
@router.post(
    "/configured",
    response_model=ChatResponse,
    summary="Générer une réponse pour les tests (utilise la personnalité de secours)"
)
async def handle_configured_chat(request: ConfiguredChatRequest):
    """
    Endpoint de test qui n'utilise que la personnalité de secours (fallback)
    car il ne reçoit pas de `persona_data` de la BDD.
    """
    # On passe un dictionnaire vide pour la personnalité, forçant l'utilisation du fallback
    dynamic_system_prompt = build_dynamic_system_prompt(
        base_persona_dict={},
        slider_settings=request.persona
    )

    messages_for_llm = [dynamic_system_prompt] + request.history + [
        {"role": "user", "content": request.message}
    ]

    try:
        response_text = await vllm_client.get_vllm_response(messages_for_llm)
        return ChatResponse(response=response_text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur interne: {e}")