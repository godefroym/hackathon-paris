# Docker Compose – Architecture & Ports

Ce document décrit l'ensemble des services définis dans `docker-compose.yml`, leurs rôles, leurs ports exposés et leurs dépendances.

---

## Vue d'ensemble

```
                        ┌─────────────────────────────────────────────────────┐
                        │                  app-network                        │
                        │                                                     │
  ┌──────────────┐       │  ┌─────────────┐   ┌──────────────┐               │
  │   mediamtx   │       │  │   app-web   │   │ veristral-web│               │
  │  (SRT/RTMP/  │       │  │  :8000      │   │  :8002       │               │
  │   RTSP/HTTP) │       │  ├─────────────┤   ├──────────────┤               │
  └──────────────┘       │  │  app-queue  │   │veristral-    │               │
                        │  │  app-reverb │   │queue/reverb  │               │
                        │  │  :8081      │   │  :8083       │               │
                        │  └─────────────┘   └──────────────┘               │
                        │                                                     │
                        │  ┌──────────────────────────────────────────────┐  │
                        │  │              temporal-network                 │  │
                        │  │                                               │  │
                        │  │  postgresql  elasticsearch  temporal          │  │
                        │  │   :5432       :9200         :7233             │  │
                        │  │                             temporal-ui       │  │
                        │  │                             :8080             │  │
                        │  └──────────────────────────────────────────────┘  │
                        │                                                     │
                        │  workflows-worker / workflows-launcher              │
                        │  (temporal-network + app-network)                  │
                        └─────────────────────────────────────────────────────┘
```

---

## Tableau des ports

| Port hôte | Port conteneur | Protocole | Service           | Usage                                  |
|-----------|---------------|-----------|-------------------|----------------------------------------|
| `1935`    | `1935`        | TCP       | `mediamtx`        | RTMP (ingestion vidéo)                 |
| `5432`    | `5432`        | TCP       | `postgresql`      | PostgreSQL (base Temporal)             |
| `7233`    | `7233`        | TCP       | `temporal`        | gRPC API Temporal                      |
| `8000`    | `8000`        | TCP       | `app-web`         | HTTP – OBS Controller (Laravel)        |
| `8002`    | `8000`        | TCP       | `veristral-web`   | HTTP – Veristral (Laravel)             |
| `8080`    | `8080`        | TCP       | `temporal-ui`     | UI Web Temporal                        |
| `8081`    | `8080`        | TCP       | `app-reverb`      | WebSocket Reverb – OBS Controller      |
| `8083`    | `8080`        | TCP       | `veristral-reverb`| WebSocket Reverb – Veristral           |
| `8554`    | `8554`        | TCP       | `mediamtx`        | RTSP                                   |
| `8888`    | `8888`        | TCP       | `mediamtx`        | API HTTP MediaMTX                      |
| `8890`    | `8890`        | **UDP**   | `mediamtx`        | SRT (streaming avec délai)             |
| `9200`    | `9200`        | TCP       | `elasticsearch`   | API HTTP Elasticsearch (visibilité)    |

---

## Services

### `mediamtx`

Serveur média multi-protocoles utilisé pour relayer les flux vidéo/audio.

| Propriété  | Valeur                        |
|------------|-------------------------------|
| Image      | `bluenviron/mediamtx:latest`  |
| Réseau     | aucun réseau nommé (bridge par défaut) |
| Config     | `./mediamtx.yml` monté dans le conteneur |

**Ports exposés :**

| Port        | Protocole | Usage                                              |
|-------------|-----------|----------------------------------------------------|
| `8890/udp`  | UDP       | **SRT** – ingestion/sortie avec latence configurable (ex : 12 s de délai pour laisser le temps au fact-checking) |
| `1935`      | TCP       | **RTMP** – ingestion classique (OBS, encodeurs)    |
| `8554`      | TCP       | **RTSP** – relecture ou ingestion RTSP             |
| `8888`      | TCP       | **API HTTP** – contrôle et monitoring MediaMTX     |

> ⚠️ Le port SRT doit impérativement être déclaré en `/udp`. SRT repose exclusivement sur UDP.

---

### `postgresql`

Base de données PostgreSQL utilisée par Temporal pour la persistance des workflows.

| Propriété     | Valeur                                          |
|---------------|-------------------------------------------------|
| Image         | `postgres:${POSTGRESQL_VERSION}`                |
| Réseau        | `temporal-network`                              |
| Credentials   | user: `temporal` / password: `temporal`         |
| Healthcheck   | `pg_isready -U temporal` toutes les 5 s         |

**Port :**

| Port   | Usage                       |
|--------|-----------------------------|
| `5432` | Accès PostgreSQL depuis l'hôte (debug/migrations manuelles) |

---

### `elasticsearch`

Moteur de recherche utilisé par Temporal pour la **visibilité des workflows** (recherche de workflows par attributs).

| Propriété     | Valeur                                          |
|---------------|-------------------------------------------------|
| Image         | `elasticsearch:${ELASTICSEARCH_VERSION}`        |
| Réseau        | `temporal-network`                              |
| Mode          | `single-node`, sans sécurité (`xpack.security.enabled=false`) |
| Heap JVM      | 256 Mo min/max                                  |
| Healthcheck   | `GET /_cluster/health?wait_for_status=yellow`   |

**Port :**

| Port   | Usage                           |
|--------|---------------------------------|
| `9200` | API REST Elasticsearch (requêtes, index) |

---

### `temporal-admin-tools` *(job one-shot)*

Conteneur d'initialisation qui exécute le script `scripts/setup-postgres-es.sh` pour créer les schémas Temporal dans PostgreSQL et Elasticsearch.

| Propriété     | Valeur                                                         |
|---------------|----------------------------------------------------------------|
| Image         | `temporalio/admin-tools:${TEMPORAL_ADMINTOOLS_VERSION}`        |
| Réseau        | `temporal-network`                                             |
| Dépend de     | `postgresql` (healthy) + `elasticsearch` (healthy)            |
| Restart       | `on-failure:6` (6 tentatives maximum)                          |

Aucun port exposé.

---

### `temporal`

Serveur Temporal – orchestrateur de workflows.

| Propriété     | Valeur                                          |
|---------------|-------------------------------------------------|
| Image         | `temporalio/server:${TEMPORAL_VERSION}`         |
| Réseau        | `temporal-network`                              |
| Dépend de     | `temporal-admin-tools` (completed_successfully) |
| Config dyn.   | `./dynamicconfig/development-sql.yaml`          |
| Healthcheck   | `nc -z localhost 7233` toutes les 5 s           |

**Port :**

| Port   | Usage                                      |
|--------|--------------------------------------------|
| `7233` | **gRPC** – API principale Temporal (workers, CLI, SDK) |

---

### `temporal-create-namespace` *(job one-shot)*

Crée le namespace `default` dans Temporal via `scripts/create-namespace.sh`.

| Propriété | Valeur                                   |
|-----------|------------------------------------------|
| Dépend de | `temporal` (healthy)                     |
| Restart   | `on-failure:5`                           |

Aucun port exposé.

---

### `temporal-ui`

Interface web officielle de Temporal pour visualiser et administrer les workflows.

| Propriété | Valeur                                       |
|-----------|----------------------------------------------|
| Image     | `temporalio/ui:${TEMPORAL_UI_VERSION}`       |
| Réseau    | `temporal-network`                           |
| Dépend de | `temporal` (healthy)                         |
| CORS      | `http://localhost:3000`                       |

**Port :**

| Port   | Usage                   |
|--------|-------------------------|
| `8080` | Interface web Temporal  |

---

### `app-web`

Application Laravel **OBS Controller** – backend HTTP principal.

| Propriété   | Valeur                                      |
|-------------|---------------------------------------------|
| Build       | `./apps/obs-controller`                     |
| Réseau      | `app-network`                               |
| Commande    | `php artisan serve --host=0.0.0.0 --port=8000` |
| Migrations  | Exécutées au démarrage (`RUN_MIGRATIONS=true`) |
| Volumes     | `storage/` et `database/` montés depuis l'hôte |
| Healthcheck | `GET /up` toutes les 10 s                   |

**Port :**

| Port   | Usage                              |
|--------|------------------------------------|
| `8000` | HTTP – API & interface OBS Controller |

---

### `app-queue`

Worker de queue Laravel pour **OBS Controller** (traitement asynchrone des jobs).

| Propriété | Valeur                                   |
|-----------|------------------------------------------|
| Réseau    | `app-network`                            |
| Dépend de | `app-web` (healthy)                      |
| Commande  | `php artisan queue:listen --tries=1 --timeout=0` |

Aucun port exposé.

---

### `app-reverb`

Serveur **WebSocket Reverb** pour OBS Controller – diffuse les événements en temps réel vers les clients front-end.

| Propriété | Valeur                                                          |
|-----------|-----------------------------------------------------------------|
| Réseau    | `app-network`                                                   |
| Dépend de | `app-web` (healthy)                                             |
| Commande  | `php artisan reverb:start --host=0.0.0.0 --port=8080`          |

**Port :**

| Port hôte | Port conteneur | Usage                                          |
|-----------|---------------|------------------------------------------------|
| `8081`    | `8080`        | **WebSocket** – pusher-compatible (Reverb) pour OBS Controller |

> Le port hôte est `8081` (et non `8080`) pour éviter le conflit avec `temporal-ui`.

---

### `veristral-web`

Application Laravel **Veristral** – backend HTTP dédié au fact-checking.

| Propriété   | Valeur                                      |
|-------------|---------------------------------------------|
| Build       | `./apps/veristral`                          |
| Réseau      | `app-network`                               |
| Commande    | `php artisan serve --host=0.0.0.0 --port=8000` |
| Migrations  | Exécutées au démarrage (`RUN_MIGRATIONS=true`) |
| Healthcheck | `GET /up` toutes les 10 s                   |

**Port :**

| Port   | Usage                      |
|--------|----------------------------|
| `8002` | HTTP – API & interface Veristral |

---

### `veristral-queue`

Worker de queue Laravel pour **Veristral**.

| Propriété | Valeur                          |
|-----------|---------------------------------|
| Réseau    | `app-network`                   |
| Dépend de | `veristral-web` (healthy)       |
| Commande  | `php artisan queue:listen --tries=1 --timeout=0` |

Aucun port exposé.

---

### `veristral-reverb`

Serveur **WebSocket Reverb** pour Veristral.

| Propriété | Valeur                                              |
|-----------|-----------------------------------------------------|
| Réseau    | `app-network`                                       |
| Dépend de | `veristral-web` (healthy)                           |
| Commande  | `php artisan reverb:start --host=0.0.0.0 --port=8080` |

**Port :**

| Port hôte | Port conteneur | Usage                                        |
|-----------|---------------|----------------------------------------------|
| `8083`    | `8080`        | **WebSocket** – pusher-compatible (Reverb) pour Veristral |

---

### `workflows-worker`

Worker Python Temporal qui exécute les **activités de fact-checking** (analyse statistique, cohérence, contexte).

| Propriété   | Valeur                                                            |
|-------------|-------------------------------------------------------------------|
| Build       | `workflows/Dockerfile` (contexte racine)                         |
| Réseaux     | `temporal-network` + `app-network`                               |
| Dépend de   | `temporal-create-namespace` (completed) + `app-web` (healthy)    |
| Commande    | `python workflows/debate_worker.py --address temporal:7233`       |
| Env clé     | `FACT_CHECK_POST_URL` → URL pour poster les résultats vers `app-web` |

Aucun port exposé.

---

### `workflows-launcher`

Utilitaire one-shot qui **injecte un fichier JSONL** dans Temporal pour démarrer un workflow de débat.

| Propriété | Valeur                                                           |
|-----------|------------------------------------------------------------------|
| Réseaux   | `temporal-network` + `app-network`                               |
| Dépend de | `temporal` (healthy)                                             |
| Restart   | `no` (usage manuel uniquement)                                   |
| Commande  | `python workflows/debate_jsonl_to_temporal.py --address temporal:7233 --input-jsonl -` |
| stdin     | Ouvert (`stdin_open: true`) – reçoit le JSONL via `docker attach` ou pipe |

Aucun port exposé.

---

## Réseaux

| Réseau            | Driver  | Rôle                                                        |
|-------------------|---------|-------------------------------------------------------------|
| `app-network`     | bridge  | Relie les applications Laravel (OBS Controller, Veristral) et les workers Python |
| `temporal-network`| bridge  | Relie l'infrastructure Temporal (serveur, DB, Elasticsearch, UI) et les workers |

Les services `workflows-worker` et `workflows-launcher` appartiennent aux **deux réseaux** pour pouvoir communiquer à la fois avec Temporal et avec `app-web`.

---

## Variables d'environnement importantes

Les versions d'images et les clés de configuration sont centralisées dans le fichier `.env` (ou `cle.env`) à la racine du projet. Les variables attendues incluent :

| Variable                      | Exemple            | Usage                                     |
|-------------------------------|--------------------|-------------------------------------------|
| `POSTGRESQL_VERSION`          | `16`               | Version de l'image PostgreSQL             |
| `ELASTICSEARCH_VERSION`       | `8.13.0`           | Version de l'image Elasticsearch          |
| `TEMPORAL_VERSION`            | `1.24.2`           | Version du serveur Temporal               |
| `TEMPORAL_ADMINTOOLS_VERSION` | `1.24.2`           | Version des admin-tools Temporal          |
| `TEMPORAL_UI_VERSION`         | `2.26.2`           | Version de l'UI Temporal                  |
| `OBS_VITE_REVERB_APP_KEY`     | -                  | Clé Reverb pour le front OBS Controller   |
| `VERISTRAL_VITE_REVERB_APP_KEY` | -               | Clé Reverb pour le front Veristral        |
| `FACT_CHECK_POST_URL`         | `http://app-web:8000/api/stream/fact-check` | URL de callback fact-check |

Voir `cle.env.example` pour la liste complète des variables.

---

## Ordre de démarrage

```
postgresql ──┐
             ├──► temporal-admin-tools ──► temporal ──► temporal-create-namespace
elasticsearch┘                                  │
                                                 ├──► temporal-ui
                                                 ├──► workflows-worker
                                                 └──► workflows-launcher

app-web ──► app-queue
        └──► app-reverb

veristral-web ──► veristral-queue
              └──► veristral-reverb
```
