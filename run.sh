#!/usr/bin/env bash
# Script pour lancer l'environnement avec un modèle spécifique.
# Usage: ./run.sh eva

set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Erreur : Veuillez spécifier le nom du modèle (ex: qwen2, midnight, eva-qwen2.5-72b)."
  echo "Modeles disponibles:"
  ls -1 models_env/*.env 2>/dev/null | sed 's#^models_env/##; s#\.env$##' || true
  exit 1
fi

MODEL_NAME="$1"
LLM_BACKEND="vllm"

if [ "$MODEL_NAME" = "grok" ]; then
  LLM_BACKEND="grok"
  MODEL_NAME="euryale"
fi

case "$MODEL_NAME" in
  qwen2)
    MODEL_NAME="qwen2"
    ;;
  qwen3)
    MODEL_NAME="qwen3"
    ;;
  midnight)
    MODEL_NAME="midnight"
    ;;
  eva|eva-qwen2.5-72b)
    MODEL_NAME="eva-qwen2.5-72b"
    ;;
esac
ENV_FILE="models_env/${MODEL_NAME}.env"

if [ ! -f "$ENV_FILE" ]; then
  echo "Erreur : Le fichier '${ENV_FILE}' n'existe pas."
  echo "Modeles disponibles:"
  ls -1 models_env/*.env 2>/dev/null | sed 's#^models_env/##; s#\.env$##' || true
  exit 1
fi

echo "[+] Lancement avec le modele : ${MODEL_NAME}"

if ! command -v docker >/dev/null 2>&1; then
  echo "Erreur : docker n'est pas installe ou n'est pas dans le PATH."
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Erreur : docker compose n'est pas disponible (plugin Compose v2 requis)."
  exit 1
fi

mkdir -p logs hf_cache

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

echo "SINHOME_LLM_BACKEND=${LLM_BACKEND}" >> "$DOTENV_FILE"

echo "[*] .env genere (contenu masque)"

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
