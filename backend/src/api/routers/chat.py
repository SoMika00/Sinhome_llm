# Fichier: backend/src/api/routers/chat.py (Version Robuste et Simplifiée)

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
    FALLBACK_PERSONALITY_DATA
)

router = APIRouter()
ext_router = APIRouter() # Pour la compatibilité Lambda

# --- Modèles Pydantic (inchangés) ---
class SimpleChatRequest(BaseModel):
    message: str = Field(...)
    history: List[Dict[str, str]] = Field(default_factory=list)

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
    persona_data: Dict[str, Any] = Field(default_factory=dict)


def _fallback_personality() -> SimpleNamespace:
    """
    Personnalité de repli complète et robuste si la BDD est indisponible ou vide.
    Cette fonction est notre filet de sécurité.
    Elle renvoie un objet complet pour que le reste du code n'échoue jamais.
    """
    # Ce log est crucial : il te dira dans les logs Docker que le plan B a été activé.
    print("[LOG] ALERTE: La personnalité de la BDD n'a pas pu être chargée. Utilisation du fallback 'Seline' par défaut.")
    
    # On transforme notre dictionnaire de secours en objet pour qu'il soit utilisable partout
    return SimpleNamespace(**FALLBACK_PERSONALITY_DATA)


# --- ENDPOINT PRINCIPAL : /configured ---
@router.post(
    "/configured",
    response_model=ChatResponse,
    summary="Générer une réponse avec une personnalité dynamique (BDD + sliders)"
)
async def handle_configured_chat(request: ConfiguredChatRequest):
    """
    Endpoint principal qui essaie de charger la personnalité depuis la BDD,
    et bascule sur le fallback en cas de problème, sans jamais planter.
    """
    TARGET_MODEL_ID = UUID("f0d654d4-96ca-4c50-af9d-5fa7009c9b67")
    base_personality = None # On initialise à None

    # --- Étape 1: Essayer de récupérer la personnalité depuis la BDD ---
    try:
        # On tente la connexion à la base de données
        base_personality = await db.get_model_by_id(TARGET_MODEL_ID)
    except Exception as e:
        # SI LA BDD CRASH (connexion impossible, etc.) :
        # On ne renvoie PAS d'erreur à l'utilisateur.
        # On log l'erreur pour toi, et on continue.
        print(f"[ERREUR] Échec de la connexion à la BDD: {e}. Le fallback sera utilisé.")
        # base_personality reste à None, ce qui déclenchera le fallback.

    # --- Étape 2: Vérifier si on a une personnalité, sinon, activer le plan B ---
    if not base_personality:
        # Ce bloc s'active si la BDD a crashé OU si le modèle n'a pas été trouvé.
        base_personality = _fallback_personality()

    # --- Étape 3: Construire le prompt et appeler le LLM ---
    # À ce stade, on a la GARANTIE que `base_personality` est un objet complet
    # (soit celui de la BDD, soit notre fallback). Le code ne peut plus planter ici.
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
        raise HTTPException(status_code=503, detail=f"Impossible de contacter le service LLM: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur interne lors de l'appel au LLM: {e}")


# --- ENDPOINT SIMPLE : / ---
@router.post(
    "/",
    response_model=ChatResponse,
    summary="Générer une réponse de chat simple (fallback sans BDD)"
)
async def handle_simple_chat(request: SimpleChatRequest):
    """Cet endpoint utilise TOUJOURS la personnalité de secours. Il est simple et fiable."""
    base_personality = _fallback_personality()
    default_sliders = PersonaSettings() # Utilise les valeurs par défaut des sliders

    dynamic_system_prompt = build_dynamic_system_prompt(
        base_personality=base_personality,
        slider_settings=default_sliders
    )

    messages_for_llm = [dynamic_system_prompt] + request.history + [
        {"role": "user", "content": request.message}
    ]

    response_text = await vllm_client.get_vllm_response(messages_for_llm)
    return ChatResponse(response=response_text)


# --- ENDPOINT LAMBDA : /personality_chat (logique inchangée mais clarifiée) ---
# Fonctions utilitaires pour Lambda (inchangées)
def _as_int(x: Any, default: int) -> int:
    try: v = int(x); return v if 1 <= v <= 5 else default
    except Exception: return default

def _persona_from_lambda_dict(d: Dict[str, Any]) -> PersonaSettings:
    return PersonaSettings(
        sales_tactic=_as_int(d.get("sales_tactic"), 2), dominance=_as_int(d.get("dominance"), 3),
        audacity=_as_int(d.get("audacity"), 3), tone=_as_int(d.get("tone"), 2),
        emotion=_as_int(d.get("emotion"), 3), initiative=_as_int(d.get("initiative"), 3),
        vocabulary=_as_int(d.get("vocabulary"), 3), emojis=_as_int(d.get("emojis"), 3),
        imperfection=_as_int(d.get("imperfection"), 1),
    )

@ext_router.post(
    "/personality_chat",
    response_model=ChatResponse,
    summary="Compatibilité Lambda: {session_id, message, history, persona_data}"
)
async def personality_chat_compat(request: LambdaChatRequest):
    """Route de compatibilité Lambda, utilise la même logique robuste que l'endpoint principal."""
    TARGET_MODEL_ID = UUID("f0d654d4-96ca-4c50-af9d-5fa7009c9b67")
    base_personality = None

    try:
        base_personality = await db.get_model_by_id(TARGET_MODEL_ID)
    except Exception as e:
        print(f"[ERREUR] Échec de la connexion à la BDD pour Lambda: {e}. Le fallback sera utilisé.")
    
    if not base_personality:
        base_personality = _fallback_personality()

    # Le reste de la logique est identique
    persona_sliders = _persona_from_lambda_dict(request.persona_data)
    dynamic_system_prompt = build_dynamic_system_prompt(
        base_personality=base_personality,
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