# backend/src/api/routers/logs.py
"""
Router pour le streaming des logs en temps réel via SSE (Server-Sent Events).
Usage: curl -N http://localhost:8000/logs/stream
"""

import asyncio
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ..services.conversation_logger import get_log_queue

logs_router = APIRouter()


async def log_event_generator():
    """
    Générateur async qui yield les logs au fur et à mesure qu'ils arrivent.
    Format SSE (Server-Sent Events).
    """
    queue = get_log_queue()
    
    # Message de bienvenue
    welcome_msg = (
        "================================================================================\n"
        "🔴 STREAMING LOGS EN TEMPS REEL - Sinhome Chat API\n"
        "================================================================================\n"
        "En attente de nouvelles conversations...\n"
        "================================================================================\n\n"
    )
    yield f"data: {welcome_msg.replace(chr(10), chr(10) + 'data: ')}\n\n"
    
    while True:
        try:
            # Attendre un nouveau log (avec timeout pour garder la connexion active)
            try:
                log_entry = await asyncio.wait_for(queue.get(), timeout=30.0)
                # Formater en SSE (chaque ligne doit être préfixée par "data: ")
                formatted_lines = []
                for line in log_entry.split("\n"):
                    formatted_lines.append(f"data: {line}")
                yield "\n".join(formatted_lines) + "\n\n"
            except asyncio.TimeoutError:
                # Heartbeat pour garder la connexion active
                yield ": heartbeat\n\n"
        except asyncio.CancelledError:
            # Connexion fermée par le client
            break
        except Exception as e:
            yield f"data: [ERREUR LOGGER] {str(e)}\n\n"


@logs_router.get(
    "/logs/stream",
    summary="Stream des logs en temps réel (SSE)",
    description="Connectez-vous à cet endpoint pour voir les logs en temps réel. "
                "Usage: curl -N http://localhost:8000/logs/stream"
)
async def stream_logs():
    """
    Endpoint SSE pour streamer les logs en temps réel.
    
    Utilisation:
    - Terminal: curl -N http://localhost:8000/logs/stream
    - Navigateur: Ouvrir directement l'URL
    """
    return StreamingResponse(
        log_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Désactive le buffering nginx si présent
        }
    )


@logs_router.get(
    "/logs/health",
    summary="Vérifier le status du système de logs"
)
async def logs_health():
    """Endpoint de santé pour le système de logs."""
    queue = get_log_queue()
    return {
        "status": "ok",
        "queue_size": queue.qsize(),
        "message": "Système de logs opérationnel. Utilisez /logs/stream pour le streaming."
    }
