# Fine-tuning Data Pipeline

## Structure

```
thune/
├── raw/                    # Donnees brutes du CRM
│   ├── conv.json           # Export complet des conversations
│   └── toparse.txt         # Fichier intermediaire
│
├── processed/              # Donnees nettoyees et classees
│   ├── dom.json            # Archetype dominant
│   ├── sell.json           # Archetype vendeur
│   ├── mixed.json          # Archetype mixte
│   └── by_archetype/       # Classification fine
│       ├── archetype_1_la_taquine_complice.json
│       ├── archetype_2_lambitieuse_passionnee.json
│       ├── archetype_3_la_reveuse_romantique.json
│       ├── archetype_4_laventuriere_creative.json
│       └── archetype_5_la_maitresse_exigeante.json
│
├── scripts/                # Scripts de traitement
│   ├── parse.py            # Convertit raw -> JSONL
│   ├── extract_archetype.py # Classe par archetype
│   ├── modif.py            # Modifie les instructions
│   └── anti_doublon.py     # Detecte les doublons
│
└── output/                 # Dataset final pour fine-tuning
    └── fine_tuning_data.jsonl
```

## Pipeline

1. **Extraction** : `conv.json` -> scripts/parse.py -> output/
2. **Classification** : scripts/extract_archetype.py -> processed/by_archetype/
3. **Validation** : scripts/anti_doublon.py
4. **Fine-tuning** : output/fine_tuning_data.jsonl

## Format de sortie attendu

```jsonl
{"messages": [
  {"role": "system", "content": "Dominance: 4/5 - Prends le controle..."},
  {"role": "user", "content": "Hey"},
  {"role": "assistant", "content": "Tiens, te voila..."}
]}
```

## Usage

```bash
cd thune/

# Parser les conversations brutes
python scripts/parse.py raw/conv.json output/fine_tuning_data.jsonl

# Extraire par archetype
python scripts/extract_archetype.py output/fine_tuning_data.jsonl

# Verifier les doublons
python scripts/anti_doublon.py output/fine_tuning_data.jsonl
```

