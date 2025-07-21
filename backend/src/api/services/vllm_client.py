# Fichier : backend/src/api/services/vllm_client.py (CORRIGÉ)

import httpx
from typing import List, Dict
from fastapi import HTTPException, status

# On importe juste 'settings', pas le SYSTEM_PROMPT qui n'est plus sa responsabilité
from ..config import settings

# --- CORRECTION : Le nom de la fonction et ses arguments sont maintenant corrects ---
async def get_vllm_response(messages: List[Dict[str, str]]) -> str:
    """
    Prend une liste de messages complète et la transmet à l'API vLLM.
    """
    url = f"{settings.VLLM_API_BASE_URL}/chat/completions"
    vllm_payload = {
        "model": settings.VLLM_MODEL_NAME,
        "messages": messages,
        "temperature": 0.75,
        "top_p": 0.9,
        "max_tokens": 1024  # Augmenté un peu pour des réponses plus longues
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            response = await client.post(url, json=vllm_payload)
            response.raise_for_status()  # Lève une exception pour les erreurs 4xx/5xx
            data = response.json()

            if "choices" in data and data["choices"]:
                return data["choices"][0]["message"]["content"].strip()
            else:
                # Si la réponse est 200 OK mais mal formée
                raise HTTPException(status_code=500, detail=f"Réponse invalide du modèle: {data}")
        
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="La requête au modèle a expiré.")
        # L'erreur httpx.ConnectError sera attrapée par le routeur