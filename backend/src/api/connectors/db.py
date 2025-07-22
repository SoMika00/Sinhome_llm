import asyncpg
from uuid import UUID
from pydantic import BaseModel, Field
from typing import List, Optional
from ..config import settings

# Modèle Pydantic qui mappe les colonnes de la table public.models
class ModelPersonality(BaseModel):
    id: UUID
    name: str
    base_prompt: str
    age: Optional[int] = None
    personality_tone: Optional[str] = None
    personality_humor: Optional[str] = None
    personality_favorite_expressions: Optional[List[str]] = Field(default_factory=list)
    preferences_interests: Optional[List[str]] = Field(default_factory=list)
    preferences_forbidden_topics: Optional[List[str]] = Field(default_factory=list)
    preferences_emoji_usage: Optional[str] = None
    interactions_message_style: Optional[str] = None

    # Permet à Pydantic de mapper correctement les noms de colonnes de la BDD
    class Config:
        from_attributes = True

async def get_model_by_id(model_id: UUID) -> Optional[ModelPersonality]:
    """
    Récupère la personnalité d'un modèle depuis la table public.models via son ID.
    """
    conn = None
    try:
        # On utilise la DATABASE_URL définie dans le .env
        conn = await asyncpg.connect(settings.DATABASE_URL)
        
        # La requête cible maintenant la table 'public.models'
        row = await conn.fetchrow(
            'SELECT * FROM public.models WHERE id = $1', model_id
        )
        
        if row:
            # Pydantic va automatiquement faire correspondre les colonnes aux champs du modèle
            return ModelPersonality.model_validate(dict(row))
        return None
    except Exception as e:
        # Fournit plus de détails en cas d'erreur
        print(f"Erreur de connexion ou de requête à la base de données: {e}")
        return None
    finally:
        if conn:
            await conn.close()