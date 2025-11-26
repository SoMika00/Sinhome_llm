import json
import sys
from collections import defaultdict

def find_duplicate_inputs(file_path):
    """
    Analyse un fichier JSON de fine-tuning et détecte les 'inputs'
    qui sont associés à plusieurs 'outputs' différents.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Erreur : Le fichier '{file_path}' n'a pas été trouvé.")
        return
    except json.JSONDecodeError:
        print(f"Erreur : Le fichier '{file_path}' n'est pas un JSON valide.")
        return

    print(f"[*] Analyse du fichier '{file_path}' pour detecter les inputs dupliques...")

    # On utilise un dictionnaire pour stocker toutes les réponses vues pour un même input.
    # defaultdict(set) est parfait pour ça : si une clé n'existe pas, il la crée
    # avec un ensemble (set) vide.
    inputs_map = defaultdict(set)

    # On parcourt chaque entrée du dataset
    for entry in data:
        # On s'assure que les clés 'input' et 'output' existent
        if 'input' in entry and 'output' in entry:
            current_input = entry['input']
            current_output = entry['output']
            
            # On ajoute l'output à l'ensemble des outputs connus pour cet input.
            # Un 'set' ne stocke que des valeurs uniques, donc si on ajoute
            # 5 fois le même output, il n'apparaîtra qu'une seule fois.
            inputs_map[current_input].add(current_output)

    # Maintenant, on cherche les problèmes.
    # Un problème, c'est un input qui a plus d'un output unique associé.
    duplicates = {}
    for input_text, outputs in inputs_map.items():
        if len(outputs) > 1:
            # On a trouvé un input avec plusieurs réponses différentes !
            duplicates[input_text] = list(outputs) # On convertit le set en liste pour l'affichage

    # --- AFFICHAGE DU RAPPORT FINAL ---
    if not duplicates:
        print("\n" + "=" * 60)
        print("[OK] Aucune duplication trouvee.")
        print("     Dataset coherent et pret pour le fine-tuning.")
        print("=" * 60 + "\n")
    else:
        print("\n" + "=" * 60)
        print(f"[ERREUR] {len(duplicates)} probleme(s) de duplication trouve(s)")
        print("         Un meme 'input' est associe a plusieurs 'outputs' differents.")
        print("-" * 60)
        
        for i, (input_text, outputs) in enumerate(duplicates.items(), 1):
            print(f"\nProbleme #{i}:")
            print(f"  INPUT (en double) : \"{input_text}\"")
            print(f"  OUTPUTS (differents) :")
            for j, output_text in enumerate(outputs, 1):
                print(f"    {j}. \"{output_text}\"")
        
        print("\n" + "=" * 60)
        print("[ACTION] Modifiez le fichier JSON pour que chaque 'input' n'ait qu'un seul 'output'.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python check_duplicates.py <nom_du_fichier.json>")
    else:
        file_to_check = sys.argv[1]
        find_duplicate_inputs(file_to_check)