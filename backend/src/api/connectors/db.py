import asyncpg
from uuid import UUID
from pydantic import BaseModel, Field
from typing import List, Optional
from ..config import settings

# Modèle Pydantic qui mappe TOUTES les colonnes nécessaires de la table public.models
class ModelPersonality(BaseModel):
    id: UUID
    name: str
    base_prompt: str
    age: Optional[int] = None
    
    # --- AJOUT DES CHAMPS PHYSIQUES MANQUANTS ---
    # On les déclare comme Optionnels pour que tout fonctionne même si
    # la valeur est nulle dans la base de données.
    gender: Optional[str] = None
    race: Optional[str] = None
    eye_color: Optional[str] = None
    hair_color: Optional[str] = None
    hair_type: Optional[str] = None
    
    # --- Champs de personnalité existants ---
    personality_tone: Optional[str] = None
    personality_humor: Optional[str] = None
    personality_favorite_expressions: Optional[List[str]] = Field(default_factory=list)
    
    # --- Champs de préférences existants ---
    preferences_interests: Optional[List[str]] = Field(default_factory=list)
    preferences_forbidden_topics: Optional[List[str]] = Field(default_factory=list)
    # Note: Dans votre BDD, 'preferences_emoji_usage' ressemble à une liste, mais est 'str' ici.
    # Je conserve 'str' pour respecter votre code original.
    preferences_emoji_usage: Optional[str] = None 
    
    # --- Champ de style d'interaction existant ---
    interactions_message_style: Optional[str] = None

    # Permet à Pydantic de mapper correctement les noms de colonnes de la BDD
    class Config:
        from_attributes = True # Pour Pydantic v2. Si v1, utilisez orm_mode = True

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
            # Pydantic va maintenant mapper TOUS les champs, y compris les nouveaux
            return ModelPersonality.model_validate(dict(row))
        return None
    except Exception as e:
        # Fournit plus de détails en cas d'erreur
        print(f"Erreur de connexion ou de requête à la base de données: {e}")
        return None
    finally:
        if conn:
            await conn.close()