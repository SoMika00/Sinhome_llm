import httpx
from ..config import settings

async def get_vllm_response(messages: list[dict]) -> str:
    url = f"{settings.VLLM_API_BASE_URL}/chat/completions"
    vllm_payload = {
        "model": settings.VLLM_MODEL_NAME,
        "messages": messages,
        "temperature": 0.75,
        "top_p": 0.9,
        "max_tokens": 500
    }

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, json=vllm_payload)
        response.raise_for_status()
        data = response.json()

    if "choices" in data and data["choices"]:
        return data["choices"][0]["message"]["content"]
    raise ValueError("Réponse VLLM invalide")
