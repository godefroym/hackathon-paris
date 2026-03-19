# /demo_data 📂

Ce dossier contient les données JSON utilisées par les agents experts pour simuler le fact-checking lors de la démo.

## 📄 Fichiers clés

*   `{nom}_hatvp.json` : Intérêts financiers et mandats d'un politicien spécifique.
*   `{nom}_archives.json` : Déclarations passées utilisées pour détecter les contradictions.

## 🔄 Comment ajouter un nouveau politicien ?

1.  Créez deux fichiers au format `{prenom}_{nom}_hatvp.json` et `{prenom}_{nom}_archives.json`.
2.  Remplissez-les en respectant le schéma des fichiers existants (voir `marc_valmont_*.json`).
3.  Lancez le pipeline avec `python launcher.py` et saisissez le nom complet du politicien. Les agents chargeront automatiquement ces fichiers.
