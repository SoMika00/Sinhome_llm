import json
import os
import sys
from collections import defaultdict

# --- CONFIGURATION DES ARCHÉTYPES ---
# On définit ici les phrases uniques qui identifient chaque archétype.
# La clé est le nom qu'on utilisera pour le fichier, la valeur est la phrase à chercher.
ARCHETYPE_IDENTIFIERS = {
    "archetype_1_la_taquine_complice": "Femme à l'esprit vif, séduisante et complice",
    "archetype_2_lambitieuse_passionnee": "Femme passionnée, directe et intense",
    "archetype_3_la_reveuse_romantique": "Femme douce, rêveuse et très à l'écoute",
    "archetype_4_laventuriere_creative": "Femme créative, imaginative et pleine d'initiative",
    "archetype_5_la_maitresse_exigeante": "Femme autoritaire, exigeante et en contrôle total"
}

def process_file_by_line(filepath, output_dir="json_fine_tuning_files"):
    """
    Lit un fichier ligne par ligne, classe chaque conversation JSON
    en fonction du contenu de son message système.
    """
    print("--- Démarrage du traitement ligne par ligne ---")

    # Prépare les conteneurs pour stocker les données
    # defaultdict(list) crée une liste vide pour chaque nouvel archétype trouvé
    archetype_conversations = defaultdict(list)
    question_answer_map = defaultdict(set)
    unclassified_count = 0
    line_number = 0

    # 1. Lecture du fichier ligne par ligne
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line_number += 1
            line = line.strip()
            
            # 2. On vérifie si la ligne peut être un JSON de conversation
            if not line.startswith('{"messages":'):
                continue

            # 3. On essaie de parser la ligne en JSON
            try:
                data = json.loads(line)
                system_content = ""
                # On cherche le contenu du message système
                for message in data.get("messages", []):
                    if message.get("role") == "system":
                        system_content = message.get("content", "")
                        break
                
                if not system_content:
                    unclassified_count += 1
                    continue

                # 4. Classification basée sur les phrases-clés
                classified = False
                for archetype_name, identifier in ARCHETYPE_IDENTIFIERS.items():
                    if identifier in system_content:
                        archetype_conversations[archetype_name].append(data)
                        classified = True
                        
                        # Ajout pour l'analyse des doublons
                        user_question, assistant_answer = "", ""
                        for msg in data.get("messages", []):
                            if msg.get("role") == "user": user_question = msg.get("content", "").strip()
                            elif msg.get("role") == "assistant": assistant_answer = msg.get("content", "").strip()
                        if user_question and assistant_answer:
                            question_answer_map[user_question].add(assistant_answer)
                            
                        break # On a trouvé, pas besoin de vérifier les autres
                
                if not classified:
                    unclassified_count += 1

            except json.JSONDecodeError:
                # Si une ligne ressemble à un JSON mais n'est pas valide, on l'ignore
                print(f"[AVERTISSEMENT] Ligne {line_number}: Impossible de parser le JSON. Ligne ignorée.")
                continue

    # 5. Création des fichiers de sortie
    if not archetype_conversations:
        print("\n[ERREUR] Aucune conversation valide et classifiable n'a été trouvée dans le fichier.")
        return

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    print(f"\n--- Création des fichiers JSON dans le dossier '{output_dir}' ---")
    for name, conversations in archetype_conversations.items():
        filename = f"{name}.json"
        filepath = os.path.join(output_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(conversations, f, indent=4, ensure_ascii=False)
        print(f"[SUCCÈS] Fichier '{filepath}' créé avec {len(conversations)} conversations.")
    
    if unclassified_count > 0:
        print(f"[INFO] {unclassified_count} conversations JSON n'ont pas pu être classées (identifiant non trouvé).")

    # 6. Rapport sur les questions en double
    print("\n--- Analyse des questions en double avec réponses différentes ---")
    found_duplicates = False
    for question, answers in question_answer_map.items():
        if len(answers) > 1:
            found_duplicates = True
            print(f"\n[!] La question suivante a {len(answers)} réponses différentes :")
            print(f"  -> QUESTION : \"{question}\"")
            print("  -> RÉPONSES :")
            for i, answer in enumerate(sorted(list(answers)), 1):
                print(f"    {i}. \"{answer}\"")
    
    if not found_duplicates:
        print("Aucune question avec des réponses différentes n'a été trouvée.")
        
    print("\n--- Script terminé ---")

# --- Point d'entrée du script ---
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"\n[ERREUR] Utilisation: python {sys.argv[0]} <nom_du_fichier.txt>")
        sys.exit(1)

    input_filename = sys.argv[1]
    
    if not os.path.exists(input_filename):
        print(f"\n[ERREUR] Le fichier '{input_filename}' est introuvable.")
        sys.exit(1)
        
    try:
        process_file_by_line(input_filename)
    except Exception as e:
        print(f"\n[ERREUR] Une erreur inattendue est survenue : {e}")
        sys.exit(1)