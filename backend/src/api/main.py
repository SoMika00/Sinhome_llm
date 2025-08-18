# Fichier : backend/src/api/main.py

from fastapi import FastAPI
from .routers import chat
from .routers.chat import ext_router  # router de compat Lambda

app = FastAPI(
    title="API de Chat RP Propre",
    description="Une API structurée professionnellement pour un chatbot de Roleplay.",
    version="2.0.0",
)

# Routes historiques (préfixées)
app.include_router(chat.router, prefix="/api/v1/chat", tags=["Chat"])

# Route de compatibilité Lambda (sans préfixe)
# -> expose POST /personality_chat
app.include_router(ext_router, tags=["LambdaCompat"])

@app.get("/", tags=["Health Check"])
def health_check():
    return {"status": "ok", "message": "API Backend fonctionnelle"}
