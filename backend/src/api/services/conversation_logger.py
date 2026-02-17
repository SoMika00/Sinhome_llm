# backend/src/api/services/conversation_logger.py
"""
Service de logging des conversations.
- Écrit les logs formatés dans des fichiers par session et par jour
- Maintient une queue async pour le streaming SSE en temps réel
"""

import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
import json

# Queue globale pour le streaming SSE
_log_queue: asyncio.Queue = asyncio.Queue()

# Chemin de base pour les logs
def _default_logs_base_dir() -> Path:
    p = Path(__file__).resolve()
    for parent in (p.parent, *p.parents):
        if (parent / "docker-compose.yml").exists() or (parent / ".git").exists():
            return parent / "logs"
    return Path("/app/logs")


LOGS_BASE_DIR = Path(os.getenv("SINHOME_LOGS_DIR", str(_default_logs_base_dir())))
CONVERSATIONS_DIR = LOGS_BASE_DIR / "conversations"
DAILY_DIR = LOGS_BASE_DIR / "daily"


def ensure_log_dirs():
    """Crée les dossiers de logs s'ils n'existent pas."""
    CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)
    DAILY_DIR.mkdir(parents=True, exist_ok=True)


def get_log_queue() -> asyncio.Queue:
    """Retourne la queue de logs pour le streaming SSE."""
    return _log_queue


def _format_timestamp() -> str:
    """Retourne un timestamp formaté."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _format_date() -> str:
    """Retourne la date du jour pour le fichier journalier."""
    return datetime.now().strftime("%Y-%m-%d")


def _extract_history_text(history: List[Dict[str, Any]]) -> str:
    """Formate l'historique de façon lisible."""
    if not history:
        return "(Aucun historique)"
    
    lines = []
    for msg in history:
        role = msg.get("role", "unknown").upper()
        content = msg.get("content", "")
        
        # Gérer le contenu multimodal (liste)
        if isinstance(content, list):
            text_parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text_parts.append(part.get("text", ""))
                elif isinstance(part, dict) and part.get("type") == "image_url":
                    text_parts.append("[IMAGE]")
            content = " ".join(text_parts)
        
        lines.append(f"[{role}]: {content}")
    
    return "\n".join(lines)


def _format_log_entry(
    endpoint: str,
    system_prompt: str,
    history: List[Dict[str, Any]],
    user_message: str,
    ai_response: str,
    session_id: Optional[str] = None,
    extra_info: Optional[Dict[str, Any]] = None,
    raw_payload: Optional[Dict[str, Any]] = None
) -> str:
    """
    Formate une entrée de log de façon lisible.
    """
    timestamp = _format_timestamp()
    separator = "=" * 80
    
    # Pas de tronquage - on affiche tout le system prompt
    system_display = system_prompt
    
    log_parts = [
        separator,
        f"[{timestamp}] ENDPOINT: {endpoint}",
    ]
    
    if session_id:
        log_parts.append(f"SESSION: {session_id}")
    
    log_parts.append(separator)
    
    # Payload brut (requête du front) - sans l'historique (affiché séparément)
    if raw_payload:
        log_parts.append("")
        log_parts.append("--- PAYLOAD (Requête brute du front, sans history) ---")
        try:
            # Copie du payload sans l'historique (déjà affiché dans HISTORIQUE)
            payload_display = {k: v for k, v in raw_payload.items() if k != "history"}
            payload_str = json.dumps(payload_display, ensure_ascii=False, indent=2)
            log_parts.append(payload_str)
        except Exception:
            log_parts.append(str(raw_payload))
    
    # System prompt (contexte)
    log_parts.append("")
    log_parts.append("--- SYSTEM PROMPT (Contexte) ---")
    log_parts.append(system_display)
    
    # Historique
    log_parts.append("")
    log_parts.append("--- HISTORIQUE ---")
    log_parts.append(_extract_history_text(history))
    
    # Question utilisateur
    log_parts.append("")
    log_parts.append("--- QUESTION UTILISATEUR ---")
    log_parts.append(user_message)
    
    # Réponse IA
    log_parts.append("")
    log_parts.append("--- REPONSE IA ---")
    log_parts.append(ai_response)
    
    # Infos supplémentaires si présentes
    if extra_info:
        log_parts.append("")
        log_parts.append("--- INFOS SUPPLEMENTAIRES ---")
        for key, value in extra_info.items():
            if isinstance(value, str) and "\n" in value:
                log_parts.append(f"{key}:")
                log_parts.append(value)
            else:
                log_parts.append(f"{key}: {value}")

    log_parts.append("")
    log_parts.append(separator)
    log_parts.append("")
    
    return "\n".join(log_parts)


def _write_to_file(filepath: Path, content: str):
    """Écrit le contenu dans un fichier (append mode)."""
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(content)
        f.write("\n")


async def log_conversation(
    endpoint: str,
    system_prompt: str,
    history: List[Dict[str, Any]],
    user_message: str,
    ai_response: str,
    session_id: Optional[str] = None,
    extra_info: Optional[Dict[str, Any]] = None,
    raw_payload: Optional[Dict[str, Any]] = None
):
    """
    Log une conversation complète.
    - Écrit dans le fichier de session (si session_id fourni)
    - Écrit dans le fichier journalier
    - Envoie dans la queue SSE pour le streaming en temps réel
    """
    ensure_log_dirs()
    
    # Formater l'entrée de log
    log_entry = _format_log_entry(
        endpoint=endpoint,
        system_prompt=system_prompt,
        history=history,
        user_message=user_message,
        ai_response=ai_response,
        session_id=session_id,
        extra_info=extra_info,
        raw_payload=raw_payload
    )
    
    # 1. Fichier par session
    if session_id:
        session_file = CONVERSATIONS_DIR / f"session_{session_id}.log"
    else:
        # Si pas de session_id, on crée un fichier avec timestamp unique
        timestamp_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        session_file = CONVERSATIONS_DIR / f"no_session_{timestamp_id}.log"
    
    _write_to_file(session_file, log_entry)
    
    # 2. Fichier journalier
    daily_file = DAILY_DIR / f"{_format_date()}.log"
    _write_to_file(daily_file, log_entry)
    
    # 3. Envoyer dans la queue SSE (non-bloquant)
    try:
        _log_queue.put_nowait(log_entry)
    except asyncio.QueueFull:
        # Si la queue est pleine, on ignore (pas de blocage)
        pass


async def log_error(
    endpoint: str,
    error_message: str,
    session_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None
):
    """
    Log une erreur de façon formatée.
    """
    ensure_log_dirs()
    
    timestamp = _format_timestamp()
    separator = "=" * 80
    
    log_parts = [
        separator,
        f"[{timestamp}] ERROR - ENDPOINT: {endpoint}",
    ]
    
    if session_id:
        log_parts.append(f"SESSION: {session_id}")
    
    log_parts.append(separator)
    log_parts.append("")
    log_parts.append("--- ERREUR ---")
    log_parts.append(error_message)
    
    if context:
        log_parts.append("")
        log_parts.append("--- CONTEXTE ---")
        log_parts.append(json.dumps(context, ensure_ascii=False, indent=2))
    
    log_parts.append("")
    log_parts.append(separator)
    log_parts.append("")
    
    log_entry = "\n".join(log_parts)
    
    # Écrire dans le fichier journalier
    daily_file = DAILY_DIR / f"{_format_date()}.log"
    _write_to_file(daily_file, log_entry)
    
    # Envoyer dans la queue SSE
    try:
        _log_queue.put_nowait(log_entry)
    except asyncio.QueueFull:
        pass
