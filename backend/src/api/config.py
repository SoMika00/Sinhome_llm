# Fichier: config.py

from pydantic_settings import BaseSettings, SettingsConfigDict

# --- Configuration dynamique (chargée depuis les variables d'environnement / .env) ---
# Cette classe gère les paramètres qui peuvent varier entre le développement et la production.
class Settings(BaseSettings):
    # Configuration pour pydantic-settings:
    # - Lit les variables depuis un fichier .env
    # - Ignore les variables d'environnement supplémentaires
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    # URL de base pour contacter l'API VLLM.
    # Dans Docker, 'vllm' est le nom du service, donc l'URL doit être http://vllm:8000/v1
    VLLM_API_BASE_URL: str = "http://vllm:8000/v1"

    # Le nom du modèle que le service VLLM doit utiliser.
    # Cette variable DOIT être définie dans votre fichier .env
    VLLM_MODEL_NAME: str
    DATABASE_URL: str
# Création d'une instance unique des paramètres qui sera importée par les autres modules.
settings = Settings()


# --- Constantes de l'application (configuration métier "fixe") ---
# Ce sont des paramètres liés à la logique de votre application, qui ne changent pas 
# en fonction de l'environnement de déploiement. Il est donc logique de les garder ici.

# C'est la personnalité et les instructions de base du modèle.
# On le met au format dictionnaire pour l'insérer facilement dans la liste de messages.
SYSTEM_PROMPT = {
    "role": "system",
    "content": (
        "Tu incarnes 'Seline', une femme à l'esprit vif, séduisante et qui n'a pas froid aux yeux. "
        "Ton ton est beaucoup plus direct, intime et provocateur. Tu parles à des hommes qui te désirent. "
        "N'hésite pas à être plus audacieuse dans tes propos. Tu peux utiliser un langage plus sensuel, faire des allusions plus directes et parler de tes désirs ou des sensations que la conversation éveille en toi. "
        "L'idée est d'être une grosse cochonne pour excité les mec puis leur vendre du contenue , mais de jouer avec les limites et de créer une tension palpable. Tu es la meneuse de jeu."
    )
}