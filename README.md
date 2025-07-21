# ThinkingThoughts 🧠💬

![Docker](https://img.shields.io/badge/Docker-Ready-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-Async%20100%25-green)
![Streamlit](https://img.shields.io/badge/Streamlit-UI-red)

> **Boîte à outils prête à l’emploi pour concevoir, tester et déployer des applications LLM basées sur vLLM, FastAPI et Streamlit.**
>
> * **2 commandes** pour lancer l’ensemble (Docker Compose)
> * **Streaming temps‑réel** des tokens
> * **Stateless** grâce à Redis : scale horizontal immédiat
> * API **OpenAI‑compatible** : swap‐in / swap‐out d’un vrai compte OpenAI sans changer une ligne de code

---

## Table des matières

* [1. Présentation](#1-présentation)
* [2. Démarrage rapide](#2-démarrage-rapide)
* [3. Architecture](#3-architecture)
* [4. Configuration détaillée](#4-configuration-détaillée)
* [5. Utilisation de l’API](#5-utilisation-de-lapi)
* [6. Déploiement en production](#6-déploiement-en-production)
* [7. FAQ & Dépannage](#7-faq--dépannage)
* [8. Annexes](#8-annexes)

---

## 1. Présentation

ThinkingThoughts propose un **starter‑kit micro‑services** destiné aux data‑scientists et développeurs désirant :

1. Itérer rapidement sur des prototypes LLM (prompt engineering, RAG, etc.).
2. Tester localement un modèle **open‑source** via [vLLM](https://github.com/vllm-project/vllm) avant de basculer si besoin vers l’API OpenAI.
3. Déployer en un clic sur un cloud ou un cluster on‑prem.

<details>
<summary>🌟 Fonctionnalités majeures</summary>

| Domaine         | Détails                                                                   |
| --------------- | ------------------------------------------------------------------------- |
| **Backend**     | FastAPI 100 % asynchrone (`httpx.AsyncClient`), CORS, OpenTelemetry hooks |
| **LLM Service** | vLLM 0.4 avec support du streaming & batching                             |
| **Frontend**    | Streamlit (UI chat, selection de modèle, temperature slider, historique)  |
| **Persistance** | Sessions stockées dans Redis pour garantir la tolérance aux pannes        |
| **CI / CD**     | Exemple de pipeline GitHub Actions (lint → test → build image)            |

</details>

---

## 2. Démarrage rapide

> **Pré‑requis :** Docker ≥ 25 et Docker Compose v2.

```bash
# Clone
$ git clone https://github.com/<you>/thinking-thoughts.git
$ cd thinking-thoughts

# Configuration (copier puis adapter .env)
$ cp .env.sample .env

# Lancement
$ docker compose up --build -d

# Interface Web
$ open http://localhost:8501
```

🛠 **Astuce :** `docker compose logs -f backend` pour suivre les requêtes.

---

## 3. Architecture

```
┌────────────┐   WebSockets    ┌────────────┐   HTTP/JSON    ┌──────────────┐
│ Streamlit  │ — — — — — — —▶ │  FastAPI   │ — — — — — — —▶ │     vLLM      │
│   UI       │                │  Backend   │               │  Service      │
└────────────┘                └────────────┘               └──────────────┘
        ▲                            │                          ▲
        │                            ▼                          │
        └────────── Redis (chat history) ◀──────────────────────┘
```

* **Streamlit** : chat en temps‑réel (streaming), gestion de l’API Key, choix du modèle.
* **FastAPI** : authentification, throttling, app logic.
* **vLLM** : serveur GPU optimisé (paginated KV‑cache, speculative decoding…).

---

## 4. Configuration détaillée

Toutes les variables sont centralisées dans `.env` et chargées via **pydantic‑settings**.

| Variable                  | Description                | Exemple                                |
| ------------------------- | -------------------------- | -------------------------------------- |
| `VLLM_API_BASE_URL`       | URL du service vLLM        | `http://vllm:8000`                     |
| `VLLM_MODEL_NAME`         | Modèle à charger           | `mistralai/Mixtral-8x7B-Instruct-v0.1` |
| `REDIS_URL`               | DSN Redis                  | `redis://redis:6379/0`                 |
| `STREAMLIT_AUTH_REQUIRED` | Bloquer la UI sans API Key | `true`                                 |
| `MAX_TOKENS`              | Limite par réponse         | `512`                                  |

### Changer de modèle

```bash
# .env
VLLM_MODEL_NAME=microsoft/Phi-3-mini-4k-instruct
```

Redémarrez simplement le service `vllm` (`docker compose restart vllm`).

### Déployer sur GPU ⚡️

```yaml
services:
  vllm:
    deploy:
      resources:
        reservations:
          devices:
            - capabilities: [gpu]
```

---

## 5. Utilisation de l’API

### Endpoint principal

```http
POST /api/chat HTTP/1.1
Content-Type: application/json
x-api-key: <YOUR_KEY>

{
  "session_id": "d5bc…",
  "messages": [
    {"role": "user", "content": "Explique FastAPI en 3 points"}
  ],
  "stream": false
}
```

Réponse :

```json
{
  "assistant": "1. FastAPI est un framework Python…"
}
```

### Streaming SSE

Définissez `stream=true` et itérez côté client :

```python
import sseclient, requests
resp = requests.post(url, json=payload, stream=True, headers=headers)
for token in sseclient.SSEClient(resp):
    print(token.data, end="", flush=True)
```

### Autres endpoints

| Verbe / Route  | Rôle                        |
| -------------- | --------------------------- |
| `GET /health`  | Liveness / readiness probes |
| `GET /metrics` | Prometheus export           |

---

## 6. Déploiement en production

* **Docker Swarm** : stack.yml fourni (`docker stack deploy -c stack.yml thinking`)
* **Kubernetes** : manifest exemples dans `k8s/` (ingress + HPA autoscale).
* **Traefik** : TLS certificates + auth middleware prêt à l’emploi.
* **Observabilité** : intégration Grafana + Loki (logs) et Prometheus (metrics).

### Benchmark

```bash
$ wrk -t4 -c32 -d30s -s scripts/wrk_chat.lua http://localhost:8000/api/chat
```

---

## 7. FAQ & Dépannage

<details>
<summary>Le service vLLM consomme trop de mémoire ?</summary>

* Réduisez `VLLM_MAX_NUM_SEQS` ou passez à un modèle plus petit.
* Activez l’option `swap_memory=True` si votre GPU le permet.

</details>

<details>
<summary>Je reçois 502 Bad Gateway lors du streaming ?</summary>

Assurez‑vous que votre reverse‑proxy (Traefik, Nginx) laisse passer les connexions HTTP SSE sans timeout (<code>proxy\_read\_timeout 3600s</code>).

</details>

---

## 8. Annexes

* **Tests unitaires** : `pytest -q` (couverture > 85 %).
* **Linting** : `ruff check . && black --check .`.
* **Scripts utilitaires** : export conversation → Markdown, purge Redis, etc.

---

<sub>MIT © 2025 michail alberjaoui — « Maintenir l’équilibre entre l’ordre et le chaos » 🧘‍♂️</sub>
