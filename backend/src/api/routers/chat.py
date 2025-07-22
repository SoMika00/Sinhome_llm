# Fichier : backend/src/api/routers/chat.py

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Dict
import httpx
from uuid import UUID
from ..connectors import db

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
    Endpoint de chat avancé qui utilise une personnalité spécifique (hardcodée)
    depuis la BDD et la module avec les réglages des sliders.
    """
    
    # ===> C'EST LA LIGNE CLÉ QUE NOUS AJOUTONS <===
    # On définit ici l'ID du modèle "Anna" que l'on veut utiliser.
    TARGET_MODEL_ID = UUID('f0d654d4-96ca-4c50-af9d-5fa7009c9b67')
    
    try:
        # 1. Récupérer la personnalité de base depuis la BDD en utilisant notre ID cible
        base_personality = await db.get_model_by_id(TARGET_MODEL_ID)
        
        if not base_personality:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Le modèle avec l'ID {TARGET_MODEL_ID} n'a pas été trouvé dans la base de données."
            )

        # 2. Construire le prompt système dynamique (cette partie ne change pas)
        dynamic_system_prompt = build_dynamic_system_prompt(base_personality, request.persona)

        # 3. Préparer les messages pour le LLM (cette partie ne change pas)
        messages_for_llm = [
            dynamic_system_prompt
        ] + request.history + [{"role": "user", "content": request.message}]

        # 4. Appeler le service vLLM (cette partie ne change pas)
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