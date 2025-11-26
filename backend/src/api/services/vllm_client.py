# Fichier : backend/src/api/services/vllm_client.py (MODIFIÉ)

import httpx
import logging
from typing import List, Dict
from fastapi import HTTPException, status

from ..config import settings

# --- NOUVEAU : Configuration et logger pour le fallback ---
logger = logging.getLogger(__name__)
MAX_RETRIES = 3 # 1 essai initial + 2 relances

# --- NOUVEAU : Fonction pour détecter les caractères chinois ---
def contains_chinese(text: str) -> bool:
    """
    Vérifie si une chaîne de caractères contient des idéogrammes chinois.
    On se base sur la plage Unicode des idéogrammes unifiés CJK.
    """
    if not isinstance(text, str):
        return False
    for char in text:
        if '\u4e00' <= char <= '\u9fff':
            return True
    return False

# --- MODIFIÉ : La fonction d'appel à vLLM intègre la logique de relance ---
async def get_vllm_response(messages: List[Dict[str, str]]) -> str:
    """
    Prend une liste de messages complète, la transmet à l'API vLLM,
    et inclut une logique de relance en cas de réponse en chinois.
    """
    url = f"{settings.VLLM_API_BASE_URL}/chat/completions"
    vllm_payload = {
        "model": settings.VLLM_MODEL_NAME,
        "messages": messages,
        "temperature": 0.75,
        "top_p": 0.9,
        "max_tokens": 1024
    }

    last_response_text = ""

    for attempt in range(MAX_RETRIES):
        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                logger.info(f"Tentative {attempt + 1}/{MAX_RETRIES} d'appel au LLM...")
                response = await client.post(url, json=vllm_payload)
                response.raise_for_status()
                data = response.json()

                if "choices" in data and data["choices"]:
                    response_text = data["choices"][0]["message"]["content"].strip()
                    last_response_text = response_text # On sauvegarde la dernière réponse obtenue

                    # Vérification du contenu
                    if not contains_chinese(response_text):
                        logger.info("Réponse valide (non-chinois) reçue.")
                        return response_text # Succès, on retourne la réponse
                    else:
                        logger.warning(
                            f"La tentative {attempt + 1} a renvoyé du chinois : '{response_text[:100]}...'. Relance en cours."
                        )
                else:
                    raise HTTPException(status_code=500, detail=f"Réponse invalide du modèle: {data}")

            except httpx.TimeoutException:
                raise HTTPException(status_code=504, detail="La requête au modèle a expiré.")
            except httpx.RequestError as e:
                # Gère les erreurs de connexion, etc.
                raise HTTPException(status_code=503, detail=f"Erreur de communication avec le service vLLM : {e}")
    
    # Si la boucle se termine, toutes les tentatives ont échoué.
    logger.error(f"Nombre maximal de {MAX_RETRIES} tentatives atteint. La dernière réponse contenait encore du chinois.")
    return last_response_text # On renvoie la dernière réponse, même si elle est en chinois.