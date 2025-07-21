# Fichier: chat.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# Imports depuis vos modules locaux
from ..config import SYSTEM_PROMPT
from ..services import history_manager, vllm_client

router = APIRouter()

class ChatRequest(BaseModel):
    session_id: str
    message: str

@router.post("/")
async def handle_chat(request: ChatRequest):
    """Gère la logique d'un échange de chat complet en orchestrant les services."""
    try:
        # 1. Utilise le service d'historique pour ajouter le message de l'utilisateur
        history_manager.add_message(request.session_id, "user", request.message)

        # 2. Récupère l'historique complet mis à jour
        conversation_history = history_manager.get_history(request.session_id)

        # 3. Prépare la liste de messages complète pour le LLM
        messages_for_llm = [SYSTEM_PROMPT] + conversation_history

        # 4. Utilise le service client VLLM pour obtenir une réponse
        seline_response_content = await vllm_client.get_vllm_response(messages_for_llm)

        # 5. Ajoute la réponse de Seline à l'historique
        history_manager.add_message(request.session_id, "assistant", seline_response_content)

        # 6. Renvoie la réponse au frontend
        return {"response": seline_response_content}

    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Erreur de communication avec le service VLLM: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Une erreur interne est survenue: {e}")