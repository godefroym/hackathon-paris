# Veristral 🎙️ — Live Fact-Checking for Broadcast

**Veristral** est un pipeline de fact-checking en temps réel conçu pour les émissions de télévision et les flux broadcast. Il combine la transcription audio instantanée, le routage intelligent via Minitral et des agents experts pour vérifier les statistiques, les conflits d'intérêts et les contradictions politiques.

---

## 🏛️ Architecture & Organisation du Dépôt

Le projet est structuré pour séparer l'ingestion de données, la logique métier des agents et l'infrastructure de diffusion.

### 📂 Guide des Dossiers

| Dossier | Responsabilité | Contenu Clé |
| :--- | :--- | :--- |
| **`ingestion/`** | **Cœur Technique** | Orchestre le flux de données du micro vers le rapport final. Contient `fact_check_pipeline.py`. |
| **`ingestion/agents/`** | **Intelligence** | Contient le routeur (`router.py`) et les agents experts (`conflict_of_interest_agent.py`, `contradiction_agent.py`). |
| **`demo_data/`** | **Données Mockées** | Fichiers JSON (`{nom}_hatvp.json`, `{nom}_archives.json`) servant de base de connaissance pour la démo. |
| **`app/`** | **Backend Web** | Application Laravel/Livewire gérant le dashboard web et l'interface utilisateur. |
| **`workflows/`** | **Automation (Temporal)** | Définition des workflows `Temporal.io` pour le traitement asynchrone et la résilience du pipeline. |
| **`scripts/`** | **DevOps / Infra** | Scripts Bash d'initialisation des bases de données (PostgreSQL, MySQL) et du serveur de mocks. |
| **`dynamicconfig/`** | **Configuration** | Paramètres de configuration dynamique pour le serveur Temporal. |
| **`_trash_bin/`** | **Archives** | Dossier de nettoyage contenant les anciens notebooks et scripts de test obsolètes. |

---

## ⚙️ Flux de Fonctionnement

1.  **Transcription (`ingestion/realtime_transcript.py`)** : Capture l'audio via PyAudio ou SRT, l'envoie à l'API Mistral Realtime et génère un flux JSONL sur la sortie standard.
2.  **Orchestration (`ingestion/fact_check_pipeline.py`)** : Lit le flux JSONL. Pour chaque phrase :
    *   Le **Router** identifie le type de claim (Stat, Position, Mention).
    *   L'**Agent adéquat** est sollicité pour une analyse (HATVP ou Archives).
    *   Le **SessionLogger** formate et écrit le résultat.
3.  **Visualisation (OBS & Web)** :
    *   Les résultats sont envoyés aux navigateurs via WebSockets (Reverb/Laravel).
    *   Un rapport Markdown cliquable (`afp_live_report.md`) est mis à jour en temps réel.

---

## 🛠️ Installation & Configuration

### Pré-requis
- Python 3.10+
- Un environnement virtuel configuré (`python -m venv venv`).
- Clés API :
    - **`MISTRAL_API_KEY` (Obligatoire)** : Gère la transcription en direct et le routage.
    - **`TAVILY_API_KEY` (Optionnel)** : Utilisé uniquement pour la recherche web réelle (RAG). Pour la démo AFP, cet aspect est simulé pour garantir la rapidité.

### Installation
```bash
pip install -r requirements.txt
```

---

## 🚀 Utilisation des Outils

### 1. Démarrage Rapide (Le Wizard)
Le script `launcher.py` est l'outil principal pour démarrer une session. Il vous guide interactivement pour :
*   Choisir la langue (FR/ENG).
*   Saisir le nom du politicien (pour charger les données `demo_data/`).
*   Définir si le flux est LIVE ou une VIDEO (filtre temporel sur les archives).
```bash
python launcher.py
```

### 2. Validation de la Démo AFP
Pour tester instantanément le pipeline avec 5 phrases prédéfinies (sans micro) :
```bash
python test_demo_afp.py
```

### 3. Infrastructure (Docker)
Pour lancer l'entierté de la stack (Temporal, MediaMTX, Laravel) :
```bash
docker-compose up -d
```

---

## 📝 Rapports de Session
Chaque claim traité est ajouté à **`afp_live_report.md`**. Ce fichier utilise le format Tableau Markdown et inclut des **Deep-Links cliquables** vers les sources officielles (Journal Officiel, HATVP) avec surlignage automatique du texte source.
