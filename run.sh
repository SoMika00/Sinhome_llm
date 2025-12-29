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

# Copie le fichier env pour docker compose
cp "$ENV_FILE" .env

echo "[*] .env genere :"
cat .env

# Valide la config interpolee
echo "[*] Validation docker compose..."
docker compose --env-file .env config >/dev/null

# Demarre les conteneurs
echo "[*] Demarrage des conteneurs..."
docker compose --env-file .env up --build -d --remove-orphans

echo
echo "[OK] Environnement demarre"
echo "     - Backend  : http://localhost:8001"
echo "     - vLLM API : http://localhost:8000/v1"
echo "     - Logs Docker (brut)   : docker compose logs -f"
echo "     - Logs lisibles (live) : curl -N http://localhost:8001/logs/stream"
echo "     - Stop     : docker compose down"
