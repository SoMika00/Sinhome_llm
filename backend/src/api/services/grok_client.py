import asyncio
import logging
from typing import Dict, List, Optional, Union

import httpx
from fastapi import HTTPException

from ..config import settings

logger = logging.getLogger(__name__)


async def get_grok_response(
    messages: List[Dict[str, str]],
    *,
    temperature: float = 0.65,
    top_p: float = 0.9,
    max_tokens: int = 256,
    stop: Optional[Union[str, List[str]]] = None,
) -> str:
    if not settings.GROK:
        raise HTTPException(status_code=500, detail="GROK API key manquante (env var GROK)")

    url = f"{settings.GROK_API_BASE_URL}/v1/chat/completions"

    payload: Dict[str, object] = {
        "model": settings.GROK_MODEL_NAME,
        "messages": messages,
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
    }
    if stop is not None:
        payload["stop"] = stop

    headers = {
        "Authorization": f"Bearer {settings.GROK}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

            choices = data.get("choices")
            if not choices:
                raise HTTPException(status_code=500, detail=f"Réponse Grok invalide: {data}")

            msg = choices[0].get("message") or {}
            content = msg.get("content")
            if not isinstance(content, str):
                raise HTTPException(status_code=500, detail=f"Réponse Grok invalide: {data}")

            return content.strip()
        except httpx.TimeoutException as e:
            raise HTTPException(status_code=504, detail=f"Grok timeout: {e}")
        except httpx.HTTPStatusError as e:
            detail = None
            try:
                detail = e.response.text
            except Exception:
                detail = str(e)
            raise HTTPException(status_code=e.response.status_code, detail=f"Grok error: {detail}")
        except httpx.RequestError as e:
            await asyncio.sleep(0)
            raise HTTPException(status_code=503, detail=f"Erreur de communication Grok: {e}")


async def get_grok_completion(
    prompt: str,
    *,
    temperature: float = 0.65,
    top_p: float = 0.9,
    max_tokens: int = 256,
    stop: Optional[Union[str, List[str]]] = None,
) -> str:
    return await get_grok_response(
        [{"role": "user", "content": prompt}],
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        stop=stop,
    )
