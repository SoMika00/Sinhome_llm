# Fichier: history_manager.py

# Dictionnaire global agissant comme base de données en mémoire.
_sessions_history = {}

def get_history(session_id: str) -> list[dict]:
    """Récupère l'historique d'une session. Renvoie une liste vide si la session est nouvelle."""
    return _sessions_history.get(session_id, [])

def add_message(session_id: str, role: str, content: str):
    """Ajoute un message à l'historique d'une session."""
    if session_id not in _sessions_history:
        _sessions_history[session_id] = []
    _sessions_history[session_id].append({"role": role, "content": content})