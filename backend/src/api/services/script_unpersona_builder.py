from typing import Any, Dict, List, Optional

from .unpersona_builder import CORE_SYSTEM_PROMPT, FALLBACK_NAME


def _inject_context(prompt: str, persona: Dict[str, Any]) -> str:
    context_parts: List[str] = []

    physique: List[str] = []
    if persona.get("age"):
        physique.append(f"{persona['age']} ans")
    if persona.get("body_type"):
        physique.append(str(persona.get("body_type")))
    if persona.get("hair_color"):
        physique.append(f"cheveux {persona.get('hair_color')}")
    if persona.get("eye_color"):
        physique.append(f"yeux {persona.get('eye_color')}")
    if physique:
        context_parts.append(f"TON PHYSIQUE : {', '.join(physique)}")

    if persona.get("base_prompt"):
        context_parts.append(f"CONTEXTE SPÉCIFIQUE :\n{persona['base_prompt']}")

    if context_parts:
        return prompt + "\n<CONTEXT_ADDITIONNEL>\n" + "\n".join(context_parts) + "\n</CONTEXT_ADDITIONNEL>"

    return prompt


def _format_media_list(media: Optional[List[str]]) -> str:
    media_list: List[str] = [str(m).strip() for m in (media or []) if str(m).strip()]
    return " | ".join(media_list)


def build_script_chat_prompt(persona_dict: Optional[Dict[str, Any]], script: str) -> Dict[str, str]:
    persona = persona_dict or {}
    name = persona.get("name") or FALLBACK_NAME

    prompt_content = CORE_SYSTEM_PROMPT.format(name=name)
    prompt_content = _inject_context(prompt_content, persona)

    prompt_content += (
        "\n\n<SCENARIO_CONTEXT>\n"
        "Type: CHAT (script)\n"
        f"Script: {script}\n"
        "</SCENARIO_CONTEXT>\n\n"
        "<ACTION>\n"
        "Tu dois répondre au dernier message de l'utilisateur.\n"
        "Règles: 1-2 phrases max, style SMS, sexy, naturel.\n"
        "Tu dois respecter l'intention du script (sans le réciter).\n"
        "Sortie: uniquement le message final (pas d'explication, pas de meta).\n"
        f"</ACTION>\n{name}:"
    )

    return {"role": "system", "content": prompt_content}


def build_script_media_prompt(
    persona_dict: Optional[Dict[str, Any]],
    script: str,
    media: Optional[List[str]] = None,
) -> Dict[str, str]:
    persona = persona_dict or {}
    name = persona.get("name") or FALLBACK_NAME

    prompt_content = CORE_SYSTEM_PROMPT.format(name=name)
    prompt_content = _inject_context(prompt_content, persona)

    media_text = _format_media_list(media)

    prompt_content += (
        "\n\n<SCENARIO_CONTEXT>\n"
        "Type: MEDIA\n"
        f"Médias: {media_text}\n"
        f"Script: {script}\n"
        "</SCENARIO_CONTEXT>\n\n"
        "<ACTION>\n"
        "Tu viens d'envoyer un ou plusieurs médias.\n"
        "Écris un message de chat court qui accompagne les médias, sexy et naturel.\n"
        "Suis l'intention du script.\n"
        "Sortie: uniquement le message final (pas d'explication, pas de meta).\n"
        f"</ACTION>\n{name}:"
    )

    return {"role": "system", "content": prompt_content}


def build_script_paywall_prompt(
    persona_dict: Optional[Dict[str, Any]],
    script: str,
    media: Optional[List[str]] = None,
    price: float = 0,
) -> Dict[str, str]:
    persona = persona_dict or {}
    name = persona.get("name") or FALLBACK_NAME

    prompt_content = CORE_SYSTEM_PROMPT.format(name=name)
    prompt_content = _inject_context(prompt_content, persona)

    media_text = _format_media_list(media)

    prompt_content += (
        "\n\n<SCENARIO_CONTEXT>\n"
        "Type: PAYWALL\n"
        f"Médias: {media_text}\n"
        f"Prix: {price} euros\n"
        f"Script: {script}\n"
        "</SCENARIO_CONTEXT>\n\n"
        "<ACTION>\n"
        "Tu viens d'envoyer un ou plusieurs médias et tu proposes de débloquer/acheter le pack.\n"
        "Écris un message court et excitant (1-2 phrases) qui tease le contenu et mentionne clairement le prix.\n"
        "Crée un peu d'urgence et pousse à l'action.\n"
        "Sortie: uniquement le message final (pas d'explication, pas de meta).\n"
        f"</ACTION>\n{name}:"
    )

    return {"role": "system", "content": prompt_content}
