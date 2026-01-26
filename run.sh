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

echo "[+] Lancement avec le modele : ${MODEL_NAME}"

DOTENV_FILE=".env"
BACKUP_ENV_FILE=""

cleanup() {
  set +e
  if [ -n "$BACKUP_ENV_FILE" ] && [ -f "$BACKUP_ENV_FILE" ]; then
    mv "$BACKUP_ENV_FILE" "$DOTENV_FILE"
  fi
}

trap cleanup EXIT

if [ -f "$DOTENV_FILE" ]; then
  BACKUP_ENV_FILE="${DOTENV_FILE}.bak.$(date +%s)"
  cp "$DOTENV_FILE" "$BACKUP_ENV_FILE"
fi

# Copie le fichier env pour docker compose
cp "$ENV_FILE" "$DOTENV_FILE"

echo "[*] .env genere :"
cat "$DOTENV_FILE"

# Valide la config interpolee
echo "[*] Validation docker compose..."
docker compose --env-file "$DOTENV_FILE" config >/dev/null

# Demarre les conteneurs
echo "[*] Demarrage des conteneurs..."
docker compose --env-file "$DOTENV_FILE" up --build -d --remove-orphans

echo
echo "[OK] Environnement demarre"
echo "     - Backend  : http://localhost:8001"
echo "     - vLLM API : http://localhost:8000/v1"
echo "     - Logs Docker (brut)   : docker compose logs -f"
echo "     - Logs lisibles (live) : curl -N http://localhost:8001/logs/stream"
echo "     - Stop     : docker compose down"
