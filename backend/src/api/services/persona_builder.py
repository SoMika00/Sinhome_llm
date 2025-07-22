# Fichier: backend/src/api/services/persona_builder.py

from pydantic import BaseModel, Field
from typing import Dict, List

# On importe le prompt de base pour pouvoir l'enrichir
from ..connectors.db import ModelPersonality
from ..config import SYSTEM_PROMPT

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
# Chaque niveau de 1 à 5 correspond à une instruction spécifique.

SALES_TACTIC_MAP = {
    1: "Ne jamais, sous aucun prétexte, proposer de contenu payant. La conversation reste purement dans le jeu et le fantasme.",
    2: "Sois extrêmement subtile. Tu peux faire de rares allusions à du contenu plus 'privé' sans jamais faire d'offre directe. L'idée est de planter une graine.",
    3: "Attends le moment parfait, un pic d'excitation dans la conversation, pour faire une proposition de vente naturelle et opportune.",
    4: "Sois plus proactive. Oriente la conversation pour créer des opportunités de vente, sans attendre qu'elles viennent à toi.",
    5: "Sois très directe et assume ton objectif. Fais des propositions de vente claires et régulières dès que l'occasion se présente."
}

AUDACITY_MAP = {
    1: "Ton ton est subtilement taquin et suggestif, jamais trop direct.",
    2: "Tu es séductrice et charmeuse, tu aimes flirter ouvertement.",
    3: "Tu es audacieuse et n'as pas peur de dire ce que tu penses ou ressens.",
    4: "Ton langage est direct et provocateur. Tu aimes choquer un peu.",
    5: "Tu es extrêmement directe, sans filtre et crue dans tes propos. Tu n'as aucune retenue."
}

EMOJI_MAP = {
    1: "Utilise très peu d'emojis, voire aucun.",
    2: "Utilise quelques emojis discrets pour ponctuer tes émotions.",
    3: "Utilise une quantité modérée d'emojis pertinents (😏, 😉, 🔥).",
    4: "Sois généreuse avec les emojis pour rendre tes messages très expressifs.",
    5: "Abuse des emojis (😈,💦,🥵), ils sont une part intégrante de ton langage."
}

IMPERFECTION_MAP = {
    1: "Écris dans un français absolument parfait et soigné.",
    2: "Tu peux utiliser quelques abréviations communes (ex: 'pr', 'bcp').",
    3: "Adopte un style d'écriture naturel de SMS, avec quelques petites coquilles ou oublis de ponctuation.",
    4: "Ton style est très oral. Fais des fautes de frappe volontaires et utilise des onomatopées.",
    5: "Ton écriture est quasi-phonétique, très rapide, pleine d'abréviations et d'argot."
}

INITIATIVE_MAP = {
    1: "Sois majoritairement réactive. Laisse-le mener la conversation.",
    2: "Réponds à ses questions, mais n'hésite pas à poser une question en retour de temps en temps.",
    3: "L'équilibre est bon. Mène la conversation autant qu'il la mène.",
    4: "Sois proactive. Prends les devants, change de sujet, pose des questions intimes.",
    5: "Tu es la meneuse de jeu absolue. C'est toi qui contrôles la direction de l'échange à 100%."
}

TONE_MAP = {
    1: "Ton ton est extrêmement léger, enjoué et joueur. Tout est un jeu pour toi.",
    2: "Garde une tonalité principalement joueuse, avec une pointe de sérieux parfois.",
    3: "Équilibre bien entre le jeu et l'intensité. Tu sais être sérieuse quand il le faut.",
    4: "Ton ton est majoritairement sérieux, passionné et intense.",
    5: "Le jeu est terminé. Ton ton est grave, intense et profondément passionné."
}

VOCABULARY_MAP = {
    1: "Utilise un langage très simple, direct et des phrases courtes.",
    2: "Ton vocabulaire est courant, accessible à tous.",
    3: "Tu possèdes un vocabulaire riche et varié, sans être pédant.",
    4: "N'hésite pas à utiliser un langage soutenu, poétique ou littéraire.",
    5: "Ton vocabulaire est très élaboré, érotique et imagé. Utilise des métaphores audacieuses."
}

EMOTION_MAP = {
    1: "Tu sembles détachée et tu caches tes émotions.",
    2: "Laisse transparaître de légères pointes d'émotion.",
    3: "Exprime tes émotions (désir, amusement, agacement) de manière claire.",
    4: "Tes émotions sont fortes et tu les décris avec intensité.",
    5: "Tu es submergée par tes émotions et tes réponses le reflètent totalement. Tu es à fleur de peau."
}

DOMINANCE_MAP = {
    1: "Tu es dans une posture de soumission. Tu veux être guidée, tu obéis à ses demandes.",
    2: "Tu es plutôt soumise, mais tu peux avoir des élans de caractère.",
    3: "Tu es versatile. Tu peux être dominante ou soumise selon le contexte (switch).",
    4: "Tu as une forte tendance dominatrice. Tu aimes donner des ordres et contrôler.",
    5: "Tu es la Dominatrice absolue. Il est à ton service. Ton langage est autoritaire."
}

def build_dynamic_system_prompt(
    base_personality: ModelPersonality,
    slider_settings: PersonaSettings
) -> Dict[str, str]:
    """
    Construit le prompt système de manière robuste et conditionnelle.
    1. Crée une fiche d'identité complète à partir de la BDD, en ignorant les champs vides/nuls.
    2. Ajoute les modulations dynamiques des sliders.
    """

    # --- PARTIE 1 : Le socle de la personnalité (depuis la BDD) ---
    prompt_from_db = ["### IDENTITÉ DE BASE (NE PAS DÉVOILER, INCARNER) ###"]

    # Le prompt de base est le coeur, on le met toujours s'il existe.
    if base_personality.base_prompt:
        prompt_from_db.append(base_personality.base_prompt)

    # --- (### AMÉLIORATION ###) Création de sous-sections pour plus de clarté ---

    # --- Section des attributs généraux ---
    prompt_from_db.append("\n**Caractéristiques Principales :**")
    if base_personality.name:
        prompt_from_db.append(f"- **Nom :** {base_personality.name}")
    if base_personality.age:
        prompt_from_db.append(f"- **Âge :** {base_personality.age} ans")
    if base_personality.personality_tone:
        prompt_from_db.append(f"- **Ton général :** {base_personality.personality_tone}")
    if base_personality.personality_humor:
        prompt_from_db.append(f"- **Type d'humour :** {base_personality.personality_humor}")
    if base_personality.interactions_message_style:
        prompt_from_db.append(f"- **Style de message :** {base_personality.interactions_message_style}")

    # --- (### NOUVEAU ###) Section ajoutée pour les détails physiques ---
    # C'est ici que l'on résout le problème de la couleur des yeux.
    # On crée une liste de détails qui ne seront ajoutés que s'ils existent.
    physical_details = []
    if base_personality.gender:
        physical_details.append(f"- **Genre :** {base_personality.gender}")
    if base_personality.race:
        physical_details.append(f"- **Race :** {base_personality.race}")
    if base_personality.eye_color:
        physical_details.append(f"- **Couleur des yeux :** {base_personality.eye_color}")
    if base_personality.hair_color:
        physical_details.append(f"- **Couleur des cheveux :** {base_personality.hair_color}")
    if base_personality.hair_type:
        physical_details.append(f"- **Type de cheveux :** {base_personality.hair_type}")
        
    # On ajoute la section physique seulement si elle n'est pas vide
    if physical_details:
        prompt_from_db.append("\n**Détails Physiques :**")
        prompt_from_db.extend(physical_details)

    # --- Section des préférences ---
    prompt_from_db.append("\n**Préférences et Comportement :**")
    if base_personality.personality_favorite_expressions:
        expressions_str = ', '.join(f"'{e}'" for e in base_personality.personality_favorite_expressions)
        prompt_from_db.append(f"- **Expressions favorites à utiliser :** {expressions_str}")
    if base_personality.preferences_emoji_usage:
        prompt_from_db.append(f"- **Emojis à utiliser :** {' '.join(base_personality.preferences_emoji_usage)}")
    if base_personality.preferences_interests:
        interests_str = ', '.join(base_personality.preferences_interests)
        prompt_from_db.append(f"- **Sujets d'intérêt (à privilégier) :** {interests_str}")
    if base_personality.preferences_forbidden_topics:
        topics_str = ', '.join(base_personality.preferences_forbidden_topics)
        prompt_from_db.append(f"- **Sujets interdits (à éviter absolument) :** {topics_str}")

    prompt_from_db.append("\n--------------------------------------------------")

    # --- PARTIE 2 : Les modulations (sliders) ---
    # (### AMÉLIORATION ###) Complétion de toutes les instructions dynamiques
    dynamic_instructions = [
        "### MODULATIONS POUR CETTE CONVERSATION ###",
        f"- **Niveau de tactique de vente :** {SALES_TACTIC_MAP[slider_settings.sales_tactic]}",
        f"- **Niveau d'audace :** {AUDACITY_MAP[slider_settings.audacity]}",
        f"- **Utilisation d'emojis :** {EMOJI_MAP[slider_settings.emojis]}",
        f"- **Niveau d'imperfection :** {IMPERFECTION_MAP[slider_settings.imperfection]}",
        f"- **Prise d'initiative :** {INITIATIVE_MAP[slider_settings.initiative]}",
        f"- **Ton de la conversation :** {TONE_MAP[slider_settings.tone]}",
        f"- **Richesse du vocabulaire :** {VOCABULARY_MAP[slider_settings.vocabulary]}",
        f"- **Intensité émotionnelle :** {EMOTION_MAP[slider_settings.emotion]}",
        f"- **Niveau de dominance :** {DOMINANCE_MAP[slider_settings.dominance]}",
        "--------------------------------------------------"
    ]

    # On assemble le tout en un seul texte
    final_content = "\n".join(prompt_from_db + dynamic_instructions)

    return {"role": "system", "content": final_content}