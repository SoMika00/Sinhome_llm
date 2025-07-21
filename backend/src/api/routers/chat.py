# Fichier : backend/src/api/routers/chat.py (CORRIGÉ)

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Dict
import httpx

# --- CORRECTION : On importe le SYSTEM_PROMPT depuis le fichier config central ---
from ..config import SYSTEM_PROMPT
from ..services import vllm_client

router = APIRouter()

class ChatRequest(BaseModel):
    message: str = Field(...)
    history: List[Dict[str, str]] = Field(default=[])

class ChatResponse(BaseModel):
    response: str

@router.post("/", response_model=ChatResponse, summary="Générer une réponse de chat")
async def handle_chat(request: ChatRequest):
    """
    Endpoint principal qui orchestre la conversation.
    """
    try:
        # --- CORRECTION : On construit la liste complète des messages ici ---
        messages_for_llm = [SYSTEM_PROMPT] + request.history + [{"role": "user", "content": request.message}]

        # --- CORRECTION : On appelle la bonne fonction avec le bon argument ---
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
            detail=f"Une erreur interne est survenue: {e}"
        )