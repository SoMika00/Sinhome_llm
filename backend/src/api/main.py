# Fichier : backend/src/api/main.py

from fastapi import FastAPI
from .routers.chat_routes import ext_router
from .routers.grok_chat import grok_router
from .routers.script_media import media_router
from .routers.script_paywall import paywall_router
from .routers.embeddings import d_router
from .routers.logs import logs_router
from .routers.v2_chat import v2_router
from .routers.fan_tracking import fan_router
from .routers.monitoring import monitoring_router
from .routers.qa_validation import qa_router
from .routers.media_tracking import media_tracker_router
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
app.include_router(grok_router, tags=["Chat"])
app.include_router(media_router, tags=["Chat"])
app.include_router(paywall_router, tags=["Chat"])
app.include_router(d_router, tags=["Embeddings"])

# Endpoints V2 : /v2/personality_chat, /v2/script_chat, /v2/script_followup
app.include_router(v2_router)

# Endpoints fan tracking : /fan/interest_score, /fan/interest_score/bulk
app.include_router(fan_router)

# Endpoints monitoring : /monitoring/health, /monitoring/metrics
app.include_router(monitoring_router)

# Endpoints QA : /qa/run, /qa/run/builtin, /qa/smoke
app.include_router(qa_router)

# Endpoints media tracking : /media/sent, /media/check_duplicates, /media/recommend
app.include_router(media_tracker_router)

# Endpoints de logs : /logs/stream, /logs/health
app.include_router(logs_router, tags=["Logs"])

@app.get("/", tags=["Health"])
def health_check():
    return {"status": "ok", "message": "API opérationnelle. Logs disponibles sur /logs/stream"}
