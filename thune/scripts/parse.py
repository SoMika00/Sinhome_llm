import json
import re

def nettoyer_html(texte_brut):
    """
    Supprime les balises HTML simples comme <p> d'une chaîne de caractères.
    """
    if not isinstance(texte_brut, str):
        return ""
    # Expression régulière pour supprimer toute balise HTML
    nettoyeur = re.compile('<.*?>')
    texte_nettoye = re.sub(nettoyeur, '', texte_brut)
    return texte_nettoye.strip()

def preparer_fichier_fine_tuning(fichier_entree, fichier_sortie):
    """
    Génère un fichier de fine-tuning au format JSONL à partir des données brutes.

    Args:
        fichier_entree (str): Chemin vers le fichier JSON source (data.json).
        fichier_sortie (str): Chemin vers le fichier JSONL de sortie.
    """
    try:
        with open(fichier_entree, 'r', encoding='utf-8') as f_in:
            conversations = json.load(f_in)

        convos_exportees = 0
        messages_exportes = 0

        with open(fichier_sortie, 'w', encoding='utf-8') as f_out:
            print("Début du traitement des conversations...")
            
            for conv in conversations:
                # Vérifie si l'utilisateur a dépensé plus de 10€
                donnees_abo = conv.get('subscribedOnData', {})
                total_depense = donnees_abo.get('totalSumm', 0)

                if total_depense > 10:
                    messages_bruts = conv.get('messages', [])
                    
                    # Ignore les conversations sans messages, même si elles ont des dépenses
                    if not messages_bruts:
                        continue

                    # Étape cruciale : trier les messages par date de création pour respecter l'ordre
                    messages_bruts.sort(key=lambda msg: msg['createdAt'])

                    messages_formates = []
                    for msg in messages_bruts:
                        # Détermine le rôle : 'assistant' si le message vient du modèle, sinon 'user'
                        role = "assistant" if msg.get('isFromModel', False) else "user"
                        
                        # Nettoie le contenu du message pour enlever les balises HTML
                        contenu_propre = nettoyer_html(msg.get('text', ''))

                        # Ajoute le message uniquement s'il n'est pas vide après nettoyage
                        if contenu_propre:
                            messages_formates.append({"role": role, "content": contenu_propre})

                    # Si la conversation contient des messages valides, on l'écrit dans le fichier
                    if messages_formates:
                        ligne_json = {"messages": messages_formates}
                        
                        # Utilise json.dumps pour convertir le dictionnaire en chaîne JSON
                        # ensure_ascii=False est important pour bien encoder les accents
                        f_out.write(json.dumps(ligne_json, ensure_ascii=False) + '\n')
                        
                        convos_exportees += 1
                        messages_exportes += len(messages_formates)

        # Affiche un rapport final
        print("\n--- Rapport de préparation pour le fine-tuning ---")
        print(f"Fichier de sortie généré : '{fichier_sortie}'")
        print(f"Nombre de conversations exportées : {convos_exportees}")
        print(f"Nombre total de messages formatés : {messages_exportes}")
        print("--- Fin du rapport ---")


    except FileNotFoundError:
        print(f"ERREUR : Le fichier '{fichier_entree}' est introuvable.")
    except json.JSONDecodeError:
        print(f"ERREUR : Le contenu du fichier '{fichier_entree}' n'est pas un JSON valide.")
    except Exception as e:
        print(f"Une erreur inattendue est survenue : {e}")

# --- Point d'entree du script ---
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) >= 3:
        fichier_entree_json = sys.argv[1]
        fichier_sortie_jsonl = sys.argv[2]
    else:
        # Chemins par defaut
        fichier_entree_json = "raw/conv.json"
        fichier_sortie_jsonl = "output/fine_tuning_data.jsonl"
    
    preparer_fichier_fine_tuning(fichier_entree_json, fichier_sortie_jsonl)