# Fichier : backend/src/api/routers/chat.py

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Dict
import httpx

# On importe maintenant le constructeur de persona et le modèle de settings
from ..services import vllm_client
from ..services.persona_builder import PersonaSettings, build_dynamic_system_prompt

router = APIRouter()

# --- MODÈLES DE REQUÊTE ---

# Modèle pour la route simple existante
class SimpleChatRequest(BaseModel):
    message: str = Field(...)
    history: List[Dict[str, str]] = Field(default=[])

# NOUVEAU modèle pour la route configurée
class ConfiguredChatRequest(BaseModel):
    message: str = Field(...)
    history: List[Dict[str, str]] = Field(default=[])
    # Le front enverra un objet contenant les valeurs de tous les sliders
    persona: PersonaSettings = Field(...)

# Modèle de réponse commun
class ChatResponse(BaseModel):
    response: str

# --- NOUVEL ENDPOINT CONFIGURÉ ---

@router.post(
    "/configured",
    response_model=ChatResponse,
    summary="Générer une réponse avec une personnalité dynamique"
)
async def handle_configured_chat(request: ConfiguredChatRequest):
    """
    Endpoint de chat avancé qui utilise les réglages de personnalité
    fournis pour générer un prompt système sur-mesure.
    """
    try:
        # 1. Construire le prompt système dynamique grâce à notre nouveau module
        dynamic_system_prompt = build_dynamic_system_prompt(request.persona)

        # 2. Préparer les messages pour le LLM
        messages_for_llm = [
            dynamic_system_prompt
        ] + request.history + [{"role": "user", "content": request.message}]

        # 3. Appeler le service vLLM (pas de changement ici)
        response_text = await vllm_client.get_vllm_response(messages_for_llm)
        
        return ChatResponse(response=response_text)
    
    except httpx.ConnectError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Impossible de se connecter au service du modèle LLM: {e}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Une erreur interne est survenue: {str(e)}"
        )

# --- ENDPOINT SIMPLE EXISTANT ---
@router.post("/", response_model=ChatResponse, summary="Générer une réponse de chat simple")
async def handle_simple_chat(request: SimpleChatRequest):
    default_persona = PersonaSettings()
    dynamic_system_prompt = build_dynamic_system_prompt(default_persona)
    messages_for_llm = [dynamic_system_prompt] + request.history + [{"role": "user", "content": request.message}]
    response_text = await vllm_client.get_vllm_response(messages_for_llm)
    return ChatResponse(response=response_text)