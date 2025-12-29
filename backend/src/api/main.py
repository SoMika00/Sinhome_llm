# Fichier : backend/src/api/main.py

from fastapi import FastAPI
from .routers.chat import ext_router
from .routers.logs import logs_router
from .services.conversation_logger import ensure_log_dirs

app = FastAPI(
    title="Sinhome Chat API",
    description="API de chat RP avec personnalité configurable et directives de scénario.",
    version="2.0.0",
)

# Créer les dossiers de logs au démarrage
ensure_log_dirs()

# Endpoints principaux : /personality_chat, /script_chat, /script_followup
app.include_router(ext_router, tags=["Chat"])

# Endpoints de logs : /logs/stream, /logs/health
app.include_router(logs_router, tags=["Logs"])

@app.get("/", tags=["Health"])
def health_check():
    return {"status": "ok", "message": "API opérationnelle. Logs disponibles sur /logs/stream"}
