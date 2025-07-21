from fastapi import FastAPI
from .routers import chat

app = FastAPI(
    title="API de Chat RP Propre",
    description="Une API structurée professionnellement pour un chatbot de Roleplay.",
    version="2.0.0"
)

app.include_router(chat.router, prefix="/api/v1/chat", tags=["Chat"])

@app.get("/", tags=["Health Check"])
def health_check():
    return {"status": "ok", "message": "API Backend fonctionnelle"}
