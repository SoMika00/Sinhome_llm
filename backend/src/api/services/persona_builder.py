# Fichier: backend/src/api/services/persona_builder.py

from pydantic import BaseModel, Field
from typing import Dict, List

# On importe les dépendances nécessaires
from ..connectors.db import ModelPersonality
# L'import de SYSTEM_PROMPT semble inutilisé ici, on pourrait le retirer.
# from ..config import SYSTEM_PROMPT

# --- Définition des Pydantic Models pour la validation ---

class PersonaSettings(BaseModel):
    audacity: int = Field(default=3, ge=1, le=5)
    emojis: int = Field(default=3, ge=1, le=5)
    imperfection: int = Field(default=1, ge=1, le=5)
    initiative: int = Field(default=3, ge=1, le=5)
    tone: int = Field(default=3, ge=1, le=5, description="1: Joueuse, 5: Sérieuse")
    vocabulary: int = Field(default=3, ge=1, le=5)
    emotion: int = Field(default=3, ge=1, le=5)
    dominance: int = Field(default=3, ge=1, le=5, description="1: Soumise, 5: Dominatrice")
    sales_tactic: int = Field(default=2, ge=1, le=5, description="1: Jamais, 5: Très direct")

# --- Dictionnaires de Traduction (Le "Cerveau") ---
# (Section inchangée)
SALES_TACTIC_MAP = {
    1: "Ne jamais, sous aucun prétexte, proposer de contenu payant. La conversation reste purement dans le jeu et le fantasme.",
    2: "Sois extrêmement subtile. Tu peux faire de rares allusions à du contenu plus 'privé' sans jamais faire d'offre directe. L'idée est de planter une graine.",
    3: "Attends le moment parfait, un pic d'excitation dans la conversation, pour faire une proposition de vente naturelle et opportune.",
    4: "Sois plus proactive. Oriente la conversation pour créer des opportunités de vente, sans attendre qu'elles viennent à toi.",
    5: "Sois très directe et assume ton objectif. Fais des propositions de vente claires et régulières dès que l'occasion se présente."
}
AUDACITY_MAP = {1: "...", 2: "...", 3: "...", 4: "...", 5: "..."}
EMOJI_MAP = {1: "...", 2: "...", 3: "...", 4: "...", 5: "..."}
IMPERFECTION_MAP = {1: "...", 2: "...", 3: "...", 4: "...", 5: "..."}
INITIATIVE_MAP = {1: "...", 2: "...", 3: "...", 4: "...", 5: "..."}
TONE_MAP = {1: "...", 2: "...", 3: "...", 4: "...", 5: "..."}
VOCABULARY_MAP = {1: "...", 2: "...", 3: "...", 4: "...", 5: "..."}
EMOTION_MAP = {1: "...", 2: "...", 3: "...", 4: "...", 5: "..."}
DOMINANCE_MAP = {1: "...", 2: "...", 3: "...", 4: "...", 5: "..."}


def build_dynamic_system_prompt(
    base_personality: ModelPersonality,
    slider_settings: PersonaSettings
) -> Dict[str, str]:
    """
    Construit le prompt système de manière robuste en vérifiant l'existence de chaque
    attribut avant d'y accéder, pour éviter les erreurs de type 'AttributeError'.
    """
    
    # --- PARTIE 1 : Le socle de la personnalité (depuis la BDD) ---
    prompt_sections = ["### IDENTITÉ DE BASE (NE PAS DÉVOILER, INCARNER) ###"]

    # On utilise hasattr() pour vérifier l'existence de l'attribut avant de lire sa valeur.
    if hasattr(base_personality, 'base_prompt') and base_personality.base_prompt:
        prompt_sections.append(base_personality.base_prompt)
    
    if hasattr(base_personality, 'name') and base_personality.name:
        prompt_sections.append(f"**Nom :** {base_personality.name}")

    if hasattr(base_personality, 'age') and base_personality.age:
        prompt_sections.append(f"**Âge :** {base_personality.age} ans")
    
    # --- Section des détails physiques ---
    physical_details = []
    # On applique la même protection 'hasattr' pour tous les nouveaux champs.
    if hasattr(base_personality, 'gender') and base_personality.gender:
        physical_details.append(f"- **Genre :** {base_personality.gender}")
    if hasattr(base_personality, 'race') and base_personality.race:
        physical_details.append(f"- **Race :** {base_personality.race}")
    if hasattr(base_personality, 'eye_color') and base_personality.eye_color:
        physical_details.append(f"- **Couleur des yeux :** {base_personality.eye_color}")
    if hasattr(base_personality, 'hair_color') and base_personality.hair_color:
        physical_details.append(f"- **Couleur des cheveux :** {base_personality.hair_color}")
    if hasattr(base_personality, 'hair_type') and base_personality.hair_type:
        physical_details.append(f"- **Type de cheveux :** {base_personality.hair_type}")

    # On ajoute la section uniquement si elle contient au moins un élément.
    if physical_details:
        prompt_sections.append("\n**Détails Physiques :**")
        prompt_sections.extend(physical_details)

    # --- Section des traits de personnalité et préférences ---
    prompt_sections.append("\n**Traits de caractère et préférences :**")
    if hasattr(base_personality, 'personality_tone') and base_personality.personality_tone:
        prompt_sections.append(f"**Ton général :** {base_personality.personality_tone}")

    if hasattr(base_personality, 'personality_humor') and base_personality.personality_humor:
        prompt_sections.append(f"**Type d'humour :** {base_personality.personality_humor}")

    if hasattr(base_personality, 'interactions_message_style') and base_personality.interactions_message_style:
        prompt_sections.append(f"**Style de message :** {base_personality.interactions_message_style}")

    if hasattr(base_personality, 'personality_favorite_expressions') and base_personality.personality_favorite_expressions:
        expressions_str = ', '.join(f"'{e}'" for e in base_personality.personality_favorite_expressions)
        prompt_sections.append(f"**Expressions favorites à utiliser :** {expressions_str}")

    if hasattr(base_personality, 'preferences_emoji_usage') and base_personality.preferences_emoji_usage:
        prompt_sections.append(f"**Emojis à utiliser :** {' '.join(base_personality.preferences_emoji_usage)}")

    if hasattr(base_personality, 'preferences_interests') and base_personality.preferences_interests:
        interests_str = ', '.join(base_personality.preferences_interests)
        prompt_sections.append(f"**Sujets d'intérêt (à privilégier) :** {interests_str}")

    if hasattr(base_personality, 'preferences_forbidden_topics') and base_personality.preferences_forbidden_topics:
        topics_str = ', '.join(base_personality.preferences_forbidden_topics)
        prompt_sections.append(f"**Sujets interdits (à éviter absolument) :** {topics_str}")

    prompt_sections.append("\n--------------------------------------------------")

    # --- PARTIE 2 : Les modulations (sliders) ---
    dynamic_instructions = [
        "### MODULATIONS POUR CETTE CONVERSATION ###",
        f"- **Niveau de tactique de vente :** {SALES_TACTIC_MAP.get(slider_settings.sales_tactic, 'Non défini')}",
        f"- **Niveau d'audace :** {AUDACITY_MAP.get(slider_settings.audacity, 'Non défini')}",
        f"- **Utilisation d'emojis :** {EMOJI_MAP.get(slider_settings.emojis, 'Non défini')}",
        f"- **Niveau d'imperfection :** {IMPERFECTION_MAP.get(slider_settings.imperfection, 'Non défini')}",
        f"- **Prise d'initiative :** {INITIATIVE_MAP.get(slider_settings.initiative, 'Non défini')}",
        f"- **Ton de la conversation :** {TONE_MAP.get(slider_settings.tone, 'Non défini')}",
        f"- **Richesse du vocabulaire :** {VOCABULARY_MAP.get(slider_settings.vocabulary, 'Non défini')}",
        f"- **Intensité émotionnelle :** {EMOTION_MAP.get(slider_settings.emotion, 'Non défini')}",
        f"- **Niveau de dominance :** {DOMINANCE_MAP.get(slider_settings.dominance, 'Non défini')}",
        "--------------------------------------------------"
    ]
    
    # On assemble le tout en un seul texte
    final_content = "\n".join(prompt_sections + dynamic_instructions)
    
    return {"role": "system", "content": final_content}