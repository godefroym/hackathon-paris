# Veristral

## Présentation du projet

Veristral est une pipeline de fact-checking temps réel pour débats, interviews et prises de parole en direct.

Le système :

1. capture l'audio depuis un micro,
2. transcrit les phrases complètes,
3. envoie chaque phrase dans Temporal,
4. analyse la phrase avec un pipeline de fact-check,
5. poste le résultat vers l'application Laravel,
6. diffuse un bandeau overlay,
7. archive la transcription complète avec les fact-checks associés.

Le dépôt contient donc trois briques principales :

- `texte/` et `ingestion/` : transcription temps réel,
- `workflows/` : orchestration Temporal + analyse,
- `app/` : API Laravel + overlay temps réel.

## Architecture complète du dépôt

Arborescence racine et niveau 2 :

```text
.
├── .docs/
│   └── obs-mediamtx-setup.md
├── .env
├── .env.example
├── .gitignore
├── .venv/
│   ├── bin/
│   ├── include/
│   ├── lib/
│   ├── .gitignore
│   └── pyvenv.cfg
├── README.md
├── Trash/
│   ├── Agents.ipynb
│   ├── README.md
│   ├── Untitled.ipynb
│   ├── activities.py
│   └── test_agents.ipynb
├── antigravity.env/
├── app/
│   ├── .dockerignore
│   ├── .editorconfig
│   ├── .env
│   ├── .env.example
│   ├── .gitattributes
│   ├── .github/
│   ├── .gitignore
│   ├── .npmrc
│   ├── .vscode/
│   ├── AGENTS.md
│   ├── Dockerfile
│   ├── README.md
│   ├── app/
│   ├── artisan
│   ├── boost.json
│   ├── bootstrap/
│   ├── composer.json
│   ├── composer.lock
│   ├── config/
│   ├── database/
│   ├── docker/
│   ├── eslint.config.js
│   ├── package.json
│   ├── phpunit.xml
│   ├── pint.json
│   ├── pnpm-lock.yaml
│   ├── public/
│   ├── resources/
│   ├── routes/
│   ├── storage/
│   ├── tests/
│   ├── tsconfig.app.json
│   ├── tsconfig.json
│   ├── tsconfig.node.json
│   └── vite.config.ts
├── cle.env
├── cle.env.example
├── debug_micro.jsonl
├── docker-compose.yml
├── dynamicconfig/
│   ├── README.md
│   ├── development-cass.yaml
│   ├── development-sql.yaml
│   └── docker.yaml
├── ingestion/
│   ├── README.md
│   ├── realtime_transcript.py
│   └── requirements.txt
├── mediamtx.yml
├── reports/
│   ├── live_transcripts/
│   └── mistral_503_discord_report_2026-03-17.md
├── requirements.txt
├── scripts/
│   ├── create-namespace.sh
│   ├── mock_fact_check_receiver.py
│   ├── run_stack.sh
│   ├── setup-cassandra-es.sh
│   ├── setup-mysql-es.sh
│   ├── setup-mysql.sh
│   ├── setup-postgres-es-tls.sh
│   ├── setup-postgres-es.sh
│   ├── setup-postgres-opensearch.sh
│   ├── setup-postgres.sh
│   └── validate-temporal.sh
├── texte/
│   ├── README.md
│   ├── realtime_transcript_elevenlabs.py
│   ├── realtime_transcript_fusion.py
│   ├── requirements.txt
│   ├── run_elevenlabs_to_temporal.sh
│   └── run_fusion_to_temporal.sh
└── workflows/
    ├── .python-version
    ├── Dockerfile
    ├── README.md
    ├── activities_emma.py
    ├── debate_config.py
    ├── debate_jsonl_to_temporal.py
    ├── debate_worker.py
    ├── debate_workflow.py
    ├── main.py
    ├── pyproject.toml
    ├── requirements.worker.txt
    ├── transcript_archive.py
    ├── uv.lock
    ├── worker.py
    └── workflows.py
```

Repères importants :

- `docker-compose.yml` : stack complète locale.
- `cle.env` : configuration principale des workflows Python.
- `texte/run_fusion_to_temporal.sh` : commande la plus directe pour lancer micro -> Temporal.
- `workflows/activities_emma.py` : logique métier principale de fact-check.
- `workflows/transcript_archive.py` : archivage de la transcription enrichie.
- `app/routes/api.php` : endpoints API de fact-check.
- `app/routes/web.php` : pages overlay.
- `reports/live_transcripts/` : sorties archivées des sessions.

## Configuration de l'environnement

### Dépendances système

Prérequis recommandés :

- Docker Desktop avec `docker compose`
- Python 3.11+
- un micro fonctionnel
- accès réseau pour appeler Mistral

Selon la machine, PyAudio peut nécessiter des dépendances système supplémentaires.

### Dépendances Python

Installer l'environnement local :

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r ingestion/requirements.txt
pip install -r texte/requirements.txt
```

### Dépendances Docker / backend

Le backend Laravel, Reverb, Temporal et le worker Python tournent via Docker :

```bash
docker compose up -d --build
```

### Fichiers d'environnement

À configurer :

- `cle.env` : configuration du pipeline Python / worker
- `app/.env` : configuration Laravel / Reverb / OBS

Création initiale :

```bash
cp cle.env.example cle.env
cp app/.env.example app/.env
```

### Clés et variables importantes

Dans `cle.env` :

- `MISTRAL_API_KEY` : obligatoire
- `FACT_CHECK_ACTIVITY_IMPL=emma`
- `FACT_CHECK_POST_URL=http://app-web:8000/api/stream/fact-check`
- `PIPELINE_LANGUAGE=fr`
- `FACT_CHECK_ANALYSIS_TIMEOUT_SECONDS=90`
- `MISTRAL_AGENT_CALL_TIMEOUT_SECONDS=20`
- `VIDEO_STREAM_DELAY_SECONDS=30` ou `0` pour les tests instantanés

Variables optionnelles utiles :

- `GEMINI_API_KEY`
- `MISTRAL_WEB_SEARCH_MODEL`
- `SOURCE_SELECTION_MODE`
- `FACT_CHECK_ANALYZE_ACTIVITY_MAX_ATTEMPTS`
- variables de backoff Mistral

Dans `app/.env` :

- `BROADCAST_CONNECTION=reverb`
- `REVERB_*`
- `VITE_REVERB_*`
- `OBS_*` si usage OBS

## Marche à suivre pour lancer le projet

### 1. Préparer l'environnement

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r ingestion/requirements.txt
pip install -r texte/requirements.txt
cp cle.env.example cle.env
cp app/.env.example app/.env
```

### 2. Remplir les variables d'environnement

Renseigner au minimum dans `cle.env` :

```env
MISTRAL_API_KEY=...
FACT_CHECK_ACTIVITY_IMPL=emma
FACT_CHECK_POST_URL=http://app-web:8000/api/stream/fact-check
PIPELINE_LANGUAGE=fr
FACT_CHECK_ANALYSIS_TIMEOUT_SECONDS=90
MISTRAL_AGENT_CALL_TIMEOUT_SECONDS=20
```

### 3. Démarrer la stack Docker

Option recommandée :

```bash
./scripts/run_stack.sh up --build
```

Option directe :

```bash
docker compose up -d --build
```

### 4. Vérifier que les services sont up

```bash
docker compose ps
docker compose logs --tail=40 workflows-worker
```

Services attendus :

- `app-web` : `http://localhost:8000`
- `temporal-ui` : `http://localhost:8080`
- `app-reverb` : `http://localhost:8081`
- `temporal` : port `7233`

### 5. Ouvrir les interfaces utiles

- Overlay : `http://localhost:8000/overlays/fact-check-2`
- Temporal UI : `http://localhost:8080/namespaces/default/workflows`

### 6. Lancer la capture micro

Lister les périphériques :

```bash
source .venv/bin/activate
python texte/realtime_transcript_fusion.py --list-devices
```

Lancer le pipeline complet micro -> Temporal :

```bash
export VIDEO_DELAY_SECONDS=0
export MAX_WAIT_NEXT_PHRASE_SECONDS=0.5
./texte/run_fusion_to_temporal.sh \
  --input-device-index 0 \
  --personne "Emma" \
  --source-video "Test micro Mac" \
  --question-posee ""
```

### 7. Vérifier les sorties

Ce qui doit apparaître :

- workflows dans Temporal UI
- bandeaux dans l'overlay
- transcription archivée dans :

```text
reports/live_transcripts/<session_id>/
```

Fichiers produits :

- `transcript.md`
- `transcript.jsonl`
- `entries/*.json`

## Troubleshooting

### Le micro ne remonte rien

Vérifications :

- lancer `python texte/realtime_transcript_fusion.py --list-devices`
- vérifier l'index du micro
- vérifier les permissions micro macOS

### `Activity task timed out`

Cause la plus fréquente :

- timeout d'analyse trop court pendant un appel Mistral

À vérifier :

- `FACT_CHECK_ANALYSIS_TIMEOUT_SECONDS`
- `MISTRAL_AGENT_CALL_TIMEOUT_SECONDS`
- ne pas relancer avec un `ANALYSIS_TIMEOUT_SECONDS=20` hérité d'un ancien test

### `post_result.status_code = 500`

Cause probable :

- erreur côté `app-web`

Commandes utiles :

```bash
docker compose logs --tail=100 app-web
docker compose logs --tail=100 app-reverb
```

### Le bandeau s'affiche en `Context` au lieu de `False claim`

Cause probable :

- verdict LLM incohérent
- résumé pas assez explicite

Le front applique maintenant une détection renforcée sur les faux chiffres, mais si besoin vérifier :

- `app/resources/js/lib/factCheck.ts`
- `overall_verdict`
- `analysis.summary`

### Le contexte ne s'affiche pas

Cause probable :

- l'agent contexte ou l'éditeur final a répondu vide

Le pipeline contient désormais un fallback `Context` pour les événements identifiables :

- JO / Jeux olympiques
- grève
- guerre
- manifestation
- élection
- loi / décret / réforme

### L'overlay ne reçoit rien

Vérifier :

- `app-web` répond bien sur `8000`
- `app-reverb` tourne
- la page overlay est rechargée après un rebuild front

Commandes utiles :

```bash
docker compose ps
docker compose logs --tail=100 app-web app-reverb workflows-worker
```

### Le worker ne charge pas la bonne implémentation

Le worker principal charge uniquement :

- `workflows/activities_emma.py`

L'ancien module a été déplacé dans :

- `Trash/activities.py`

### Les transcriptions archivées n'apparaissent pas

Vérifier :

- que le workflow va jusqu'au bout
- que `archive_result.archived` vaut `true`
- que le dossier de session existe sous `reports/live_transcripts/`

### Arrêter proprement la stack

```bash
./scripts/run_stack.sh down
```

ou :

```bash
docker compose down
```
