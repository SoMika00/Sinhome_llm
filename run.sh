#!/bin/bash

# Fichier: run.sh (CORRIGÉ)
# Script pour lancer l'environnement avec un modèle spécifique.

set -e

# 1. Vérifier qu'un nom de modèle est fourni
if [ -z "$1" ]; then
  echo " Erreur : Veuillez spécifier le nom du modèle."
  echo "   Exemple: $0 production-qwen2.5-32b"
  exit 1
fi

MODEL_NAME=$1
ENV_FILE="models_env/${MODEL_NAME}.env"

# 2. Vérifier que le fichier d'environnement existe
if [ ! -f "$ENV_FILE" ]; then
  echo " Erreur : Le fichier de configuration '$ENV_FILE' n'existe pas."
  exit 1
fi

echo " Lancement de l'environnement avec le modèle : ${MODEL_NAME}"

# 3. Copier la configuration du modèle choisi dans le fichier .env principal
cp "$ENV_FILE" .env

# 4. Ajouter la DATABASE_URL de manière sécurisée
#    On vérifie d'abord si la variable n'existe pas déjà.
if ! grep -q "DATABASE_URL" .env; then
  # LA CORRECTION EST ICI :
  # On ajoute un saut de ligne AVANT d'écrire la variable.
  # C'est ce qui empêche la valeur de se coller à la ligne précédente.
  echo "" >> .env
  echo "DATABASE_URL=postgresql+asyncpg://user:password@host:port/dbname" >> .env
fi

# 5. Lancer Docker Compose
echo " Démarrage des conteneurs Docker..."
docker compose up --build -d --remove-orphans

echo "Environnement démarré avec succès !"
echo "   - Interface Streamlit : http://localhost:8501"
echo "   - Logs du modèle LLM : docker compose logs -f vllm"
echo "   - Pour tout arrêter   : docker compose down"