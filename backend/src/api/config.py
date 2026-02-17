from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """
    Gère les paramètres chargés depuis les variables d'environnement.
    La connexion à la base de données a été supprimée car le service est stateless.
    """
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    # Choix du backend LLM utilisé par les endpoints ("grok" ou "vllm").
    SINHOME_LLM_BACKEND: str = "vllm"

    # URL de base pour contacter l'API VLLM (obligatoire).
    VLLM_API_BASE_URL: str = "http://vllm:8000/v1"

    # Le nom du modèle que le service VLLM doit utiliser (obligatoire).
    VLLM_MODEL_NAME: str

    # --- Grok (xAI) ---
    GROK: str | None = None
    GROK_API_BASE_URL: str = "https://api.x.ai"
    GROK_MODEL_NAME: str = "grok-4"

# Instance unique des paramètres pour toute l'application.
settings = Settings()