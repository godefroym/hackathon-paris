🛡️ Vériscope - Hackathon Mistral AI 2026
1. Description du Problème
Dans le tumulte des campagnes électorales, le fact-checking traditionnel souffre d'un défaut majeur : l'asynchronisme. Une affirmation fausse est prononcée en direct, devient virale en quelques minutes, tandis que le démenti n'arrive que le lendemain.

Le citoyen est exposé à trois types de distorsions :

La distorsion statistique : Manipulation de chiffres complexes (PIB, chômage) difficiles à vérifier instantanément.

La distorsion rhétorique (Esquive) : La "langue de bois" où le candidat évite de répondre à une question précise.

La distorsion de cohérence : Des retournements de veste rapides (moins de 6 mois) qui passent inaperçus dans le flux d'informations.

Vériscope résout ce problème en proposant une "War Room" citoyenne capable d'analyser, de sourcer et de contextualiser le discours politique avec une latence inférieure à 10 secondes.

2. L'Architecture Technique (Stack Mistral)
Transcription (STT) : Voxtral-realtime-latest (Mistral AI).

Raisonnement & Analyse : Mistral-Small-latest (Router) & Mistral-Large-latest (Expert).

Monitoring : Weights & Biases (Weave) pour le tracking des prompts.

Données Externes : API Google Search (Filtrée sur sources institutionnelles).

Interface : Dashboard temps réel (React ou Streamlit).

3. Connexion des Tâches (Le Protocole d'Échange)
Pour que vous ne vous bloquiez pas mutuellement, vous allez fonctionner avec un système de Producteur/Consommateur basé sur un fichier JSON partagé ou une file d'attente (Queue).

🛠️ Rôle 1 : Numéricien 1 (Le Pipe Audio)
Mission : Transformer le son en texte brut.

Entrée : Flux audio YouTube.

Action : Envoie des chunks audio à Voxtral.

Connexion : Il écrit le résultat dans un objet Python (ou un fichier stream_text.json) sous cette forme :

JSON
{ "timestamp": "12:05", "raw_text": "Le chômage a baissé de 2%." }
🧠 Rôle 2 : Numéricienne 2 (Le Cerveau - Toi)
Mission : Transformer le texte brut en analyse structurée.

Entrée : Lit le raw_text de Numéricien 1.

Action :

Route via Mistral Small.

Si Statistique : Lance la recherche Google + Analyse Mistral Large.

Si Esquive/Contexte : Analyse directe Mistral Large.

Connexion : Elle produit le JSON final (Le Contrat) et l'envoie au Dev Web.

💻 Rôle 3 : Dev Web (L'Interface)
Mission : Rendre l'analyse lisible et immédiate.

Entrée : Lit le JSON final produit par Numéricienne 2.

Action : Met à jour la Timeline en injectant la nouvelle carte avec le bon code couleur (Vert/Orange/Rouge).

Connexion : Il travaille en autonomie avec un fichier mock_data.json jusqu'à ce que les numériciens branchent le flux réel.

4. Le Contrat de Données (L'Interface Commune)
C'est le point de rencontre obligatoire de vos trois codes.

JSON
{
  "id": "uuid",
  "timestamp": "HH:MM:SS",
  "category": "STAT | ESQUIVE | CONTEXT | CONTRADICTION",
  "raw_input": "La phrase du politique",
  "analysis": {
    "verdict": "green | orange | red | blue",
    "title": "Titre court",
    "explanation": "Explication pédagogique de Mistral Large",
    "source_url": "Lien vers la preuve",
    "confidence_score": 0.95
  }
}
5. Timeline du Sprint
Samedi 13h-15h : Stabilisation des pipelines individuels (STT pour N1, Prompts pour N2, UI pour Web).

Samedi 15h-19h : Développement des modules d'analyse (Stats et Esquive).

Samedi 19h-23h : Premier "Frankenstein" (Connexion des 3 rôles).

Dimanche 08h-11h : Débogage final et Code Freeze.

Dimanche 11h-15h : Enregistrement démo et Pitch.

Conseil pour la connexion :
Utilisez un dossier partagé sur un GitHub commun.

Numéricien 1 travaille dans ingestion/.

Numéricienne 2 travaille dans analysis/.

Dev Web travaille dans frontend/.
