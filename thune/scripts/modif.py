import json
import sys

# --- CONFIGURATION ---
NEW_INSTRUCTION = "Ta mission : prendre et conserver l'initiative dans un jeu de rôle érotique. Tes réponses doivent être courtes, directes et proactives. Le but est de guider la conversation, de faire avancer le scénario et d'intensifier la tension, jamais d'être passive."
OLD_INSTRUCTION = "Ta mission : incarner une personnalité féminine dominante et provocatrice dans un jeu de rôle érotique. Tes réponses doivent être courtes, directes et viser à déstabiliser l'utilisateur pour prendre le contrôle."
# ---------------------

def update_json_file(file_path):
    """
    Ouvre un fichier JSON, change la valeur de la clé 'instruction' et réécrit le fichier.
    """
    try:
        # Ouvre le fichier en lecture avec un encodage qui gère les accents
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Erreur : Le fichier '{file_path}' n'a pas été trouvé.")
        return
    except json.JSONDecodeError:
        print(f"Erreur : Le fichier '{file_path}' n'est pas un JSON valide.")
        return

    # Compteur pour savoir combien d'entrées ont été modifiées
    updated_count = 0

    # On parcourt chaque dictionnaire (chaque paire Q/R) dans la liste
    for entry in data:
        # On vérifie si la clé 'instruction' existe et si sa valeur correspond à l'ancienne
        if 'instruction' in entry and entry['instruction'] == OLD_INSTRUCTION:
            entry['instruction'] = NEW_INSTRUCTION
            updated_count += 1

    # On réécrit le fichier entier avec les données mises à jour
    with open(file_path, 'w', encoding='utf-8') as f:
        # json.dump réécrit proprement le JSON.
        # indent=2 garde le fichier lisible pour un humain.
        # ensure_ascii=False préserve les accents.
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Opération terminée. {updated_count} instructions ont été mises à jour dans '{file_path}'.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python update_instructions.py <nom_du_fichier.json>")
    else:
        file_to_update = sys.argv[1]
        update_json_file(file_to_update)