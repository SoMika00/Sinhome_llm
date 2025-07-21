# Utiliser une image de base NVIDIA CUDA avec les outils de développement
FROM nvidia/cuda:12.1.1-devel-ubuntu22.04

# Installer les dépendances système de base et Python
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    python3.10 \
    python3-pip \
    git \
    && rm -rf /var/lib/apt/lists/*

# Définir le répertoire de travail
WORKDIR /app

# Copier le fichier des dépendances que nous avons généré
COPY vllm.requirements.txt .

# Installer toutes les dépendances Python de votre environnement (vision)
# Ceci est l'étape la plus importante
RUN pip3 install -r vllm.requirements.txt

# Exposer le port sur lequel VLLM va écouter
EXPOSE 8000

# La commande par défaut pour lancer le serveur.
# Notez que les arguments comme le modèle, etc., seront passés depuis docker-compose.yml
ENTRYPOINT ["python3", "-m", "vllm.entrypoints.openai.api_server"]