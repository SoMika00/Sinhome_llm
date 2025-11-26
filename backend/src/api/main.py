# Fichier : backend/src/api/main.py

from fastapi import FastAPI
from .routers.chat import ext_router

app = FastAPI(
    title="Sinhome Chat API",
    description="API de chat RP avec personnalité configurable et directives de scénario.",
    version="2.0.0",
)

# Endpoints principaux : /personality_chat et /script_chat
app.include_router(ext_router, tags=["Chat"])

@app.get("/", tags=["Health"])
def health_check():
    return {"status": "ok", "message": "API opérationnelle"}
