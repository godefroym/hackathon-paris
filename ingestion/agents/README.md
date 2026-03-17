# /ingestion/agents 🤖

Ce dossier contient l'intelligence de classification et d'analyse du projet Veristral.

## 🧩 Composants

*   `router.py` : Routeur Minitral utilisant un scoring pondéré par mots-clés pour aiguiller les phrases vers l'agent adéquat.
*   `conflict_of_interest_agent.py` : Scrutine les données HATVP pour détecter des mandats ou intérêts dans des secteurs mentionnés.
*   `contradiction_agent.py` : Compare la transcription actuelle avec les archives passées (filtrage par année inclus).

## 🛠️ Modification des comportements

Pour ajuster la sensibilité du routage (ex: ajouter de nouveaux mots-clés sectoriels), intervenez dans `router.py`. Les poids sont configurables en haut du fichier.
