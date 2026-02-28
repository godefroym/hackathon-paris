🛡️ Vériscope - Hackathon Mistral AI 2026
1. Description du Problème
Dans le tumulte des campagnes électorales, le fact-checking traditionnel souffre d'un défaut majeur : l'asynchronisme. Une affirmation fausse est prononcée en direct, devient virale en quelques minutes, tandis que le démenti n'arrive que le lendemain.

Le citoyen est exposé à trois types de distorsions :

La distorsion statistique : Manipulation de chiffres complexes (PIB, chômage) difficiles à vérifier instantanément.

La distorsion rhétorique (Esquive) : La "langue de bois" où le candidat évite de répondre à une question précise.

La distorsion de cohérence : Des retournements de veste rapides (moins de 6 mois) qui passent inaperçus dans le flux d'informations.

Le manque de contexte 

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

# Structure 

Blocs concernés : Virtual mic ➔ (Nouveau sous-système de buffer)

Le rôle : Capturer le son sans interruption et préparer les blocs superposés.

Entrée : Flux audio brut (ex: PCM, 16kHz) en continu depuis la vidéo/le micro.

Sortie : Un fichier temporaire ou un buffer en mémoire contenant exactement les 20 dernières secondes d'audio, généré strictement toutes les 10 secondes.

Comment l'implémenter : * Utilisez un script Python asynchrone avec une structure de données collections.deque (taille fixe correspondant à 20s d'échantillons).

L'audio entre en continu d'un côté. Toutes les 10 secondes, une tâche asyncio "photographie" l'état actuel du deque et l'envoie au bloc suivant.

2. Transcription Vocale (STT)
Blocs concernés : STT ➔ Voxtral Realtime

Le rôle : Transformer le bloc audio de 20s en texte.

Entrée : Le chunk audio de 20 secondes.

Sortie : Une chaîne de caractères (String) brute. Attention : à cause de la fenêtre glissante, la première moitié de ce texte sera quasiment identique à la seconde moitié du texte généré 10 secondes plus tôt.

Outils recommandés : Voxtral (si disponible via Mistral), ou des API ultra-rapides comme Groq (Whisper) ou Deepgram pour minimiser la latence.

3. Triage, Extraction et "Semantic Cache" (Le Filtre Anti-Doublon)
Bloc concerné : Minitral (classification)

Le rôle : Extraire les affirmations pertinentes et, surtout, bloquer les doublons créés par le chevauchement audio pour ne pas spammer OBS.

Entrée : La chaîne de caractères brute de 20s.

Sortie : Un objet JSON strict contenant uniquement les nouvelles affirmations vérifiables.

JSON
{
  "nouvelles_affirmations": [
    {"id": "aff_12", "texte": "Le chômage a baissé de 10% depuis mon élection."}
  ]
}
Outils recommandés : Modèle rapide (ex: ministral-8b) en mode JSON.

Comment l'implémenter :

Prompt : Demandez au modèle d'extraire sous forme de liste les affirmations factuelles.

Le Cache (Code Python) : Stockez en mémoire les affirmations des 60 dernières secondes. Quand Minitral sort une liste d'affirmations pour le bloc actuel, comparez-les rapidement au cache (avec une fonction de similarité textuelle comme TF-IDF ou un calcul de distance de Levenshtein très basique). Si l'affirmation a déjà été analysée il y a 10 secondes, elle est supprimée de la liste. Seules les nouvelles affirmations passent à l'étape suivante.

4. Les 3 Agents d'Analyse (Exécution Parallèle)
Blocs concernés : Statistique, Distorsion rhétorique, Cohérence + Tools (web search, mcp, rag)

Le rôle : Vérifier l'affirmation sous trois angles différents simultanément.

Entrée : L'objet JSON de la nouvelle affirmation extraite.

Sortie : 3 rapports distincts au format JSON.

JSON
{
  "agent": "distorsion_rhetorique",
  "verdict": "trompeur",
  "type": "homme_de_paille",
  "explication": "Le locuteur invente un argument que son adversaire n'a jamais prononcé pour le discréditer."
}
Outils recommandés : * Agent 1 (Stats) : mistral-small + Tool Web Search (ex: Tavily).

Agent 2 (Rhétorique) : mistral-large (nécessite beaucoup de finesse de raisonnement, pas d'outil externe nécessaire).

Agent 3 (Cohérence) : mistral-small + MCP connecté à une base vectorielle (RAG) contenant les archives du candidat.

Comment l'implémenter : Utilisez impérativement asyncio.gather() en Python. Les trois appels d'API vers Mistral doivent partir à la milliseconde près en même temps.

5. Agrégation et Action TV (Tool Calling OBS)
Blocs concernés : Mistral 3 (agrégation) ➔ Tools (changement de scène) ➔ OBS

Le rôle : Prendre une décision finale et l'afficher à l'écran en direct.

Entrée : Une liste regroupant les 3 JSON générés par les agents parallèles.

Sortie : L'exécution d'un appel de fonction (Tool Calling) qui déclenche une requête WebSocket.

Outils recommandés : mistral-large-latest avec Function Calling, et la librairie Python obs-websocket-py.

Comment l'implémenter :

Mistral reçoit un prompt système lui demandant de faire la synthèse des 3 agents. S'il y a un consensus sur le fait que la phrase est fausse/trompeuse, le modèle déclenche l'outil fourni : update_obs_alert(verdict_type, short_summary, source).

Votre script Python intercepte cet appel de fonction et envoie une commande WebSocket à OBS pour rendre visible un groupe d'éléments (un calque texte avec le résumé + un fond de couleur) pendant 5 à 10 secondes, avant de le masquer à nouveau.
