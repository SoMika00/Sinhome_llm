#!/usr/bin/env bash
# Script pour lancer l'environnement avec un modèle spécifique.
# Usage: ./run.sh production-qwen2.5-32b

set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Erreur : Veuillez spécifier le nom du modèle (ex: production-qwen2.5-32b)."
  exit 1
fi

MODEL_NAME="$1"
ENV_FILE="models_env/${MODEL_NAME}.env"

if [ ! -f "$ENV_FILE" ]; then
  echo "Erreur : Le fichier '${ENV_FILE}' n'existe pas."
  exit 1
fi

echo "▶️  Lancement avec le modèle : ${MODEL_NAME}"

# 1) Fabrique un .env propre pour docker compose (dans le même dossier que docker-compose.yml)
cp "$ENV_FILE" .env

# 2) Ajoute DATABASE_URL si absente (avec saut de ligne avant)
if ! grep -qE '^DATABASE_URL=' .env; then
  printf "\n" >> .env
  echo "DATABASE_URL=postgresql+asyncpg://user:password@host:port/dbname" >> .env
fi

echo "ℹ️  .env généré :"
cat .env

# 3) Valide la config interpolée (hérite de .env)
echo "🔎 Validation docker compose (interpolation)..."
docker compose --env-file .env config >/dev/null

# 4) Démarre (on force l'env-file pour lever toute ambiguïté)
echo "🚀 Démarrage des conteneurs..."
docker compose --env-file .env up --build -d --remove-orphans

echo
echo "✅ Environnement démarré"
echo "   - Streamlit : http://localhost:8501"
echo "   - vLLM API  : http://localhost:8000/v1"
echo "   - Logs vllm : docker compose logs -f vllm"
echo "   - Stop      : docker compose down"
