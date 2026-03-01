# 🛡️ Vériscope

**Real-time AI fact-checking for live political debates, powered by Mistral AI.**

Vériscope captures a live TV debate audio stream, transcribes it in real time, runs multi-agent AI analysis on every claim, and overlays sourced verdicts on the broadcast — all within seconds.

Built during the **Mistral AI Hackathon Paris 2026**.

## The Problem

Traditional fact-checking is asynchronous: a false claim goes viral in minutes, but the correction only arrives the next day. Citizens watching a live political debate have no immediate way to verify what is being said.

Vériscope targets four types of distortion:

| Distortion | Description |
|---|---|
| **Statistical** | Manipulation or misquoting of official figures (GDP, unemployment, budgets) |
| **Rhetorical (Evasion)** | "Langue de bois" — the speaker dodges the journalist's question |
| **Coherence** | Contradictions with the speaker's own past public statements |
| **Missing Context** | Claims that are technically accurate but misleading without surrounding facts |

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Live Audio Stream                            │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  ingestion/  — realtime_transcript.py                               │
│  Mic → Voxtral Realtime STT → JSONL stream (1 line per sentence)   │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ stdout (JSONL)
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  workflows/  — Temporal Orchestration                               │
│                                                                     │
│  debate_jsonl_to_temporal.py  reads JSONL, starts 1 workflow/line   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  Temporal Workflow  (debate_workflow.py)                     │    │
│  │                                                             │    │
│  │  1. analyze_debate_line     ─── Mistral AI Agent Pipeline   │    │
  │     (retry ×3, backoff 2 s – 20 s)                         │    │
  │  2. check_self_correction   ─── Heuristic + LLM fallback   │    │
  │     (retry ×2; failure → no-correction default)            │    │
  │  3. wait for video delay    ─── Sync with live broadcast    │    │
  │  4. post_fact_check_result  ─── HTTP POST to app/           │    │
  │     (retry ×5, backoff 2 s – 30 s)                         │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                     │
│  Mistral AI Agent Pipeline:                                         │
│  ┌────────┐   ┌────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │ Routeur ├──▶│ Stats  │ │Rhétorique│ │Cohérence │ │ Contexte │   │
│  │ (route) │   │(search)│ │(analyze) │ │ (search) │ │ (search) │   │
│  └────────┘   └───┬────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘   │
│                   └───────────┴────────────┴────────────┘          │
│                               │                                     │
│                        ┌──────┴──────┐                              │
│                        │   Éditeur   │  ← synthesizes TV verdict    │
│                        └─────────────┘                              │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ HTTP POST  /api/stream/fact-check
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  app/  — Laravel 12 + Inertia.js + Vue 3                           │
│                                                                     │
│  Receives verdict → broadcasts via Laravel Reverb (WebSocket)       │
│  → Vue overlay component renders on OBS browser source              │
│  → OBS scene switch (obs-websocket-php) to show/hide the overlay    │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  facts/  — Laravel 12 (persistence API)                             │
│  Stores verified facts for later consultation (POST /api/facts)     │
└─────────────────────────────────────────────────────────────────────┘
```

## Tech Stack

| Layer | Technology |
|---|---|
| Speech-to-Text | **Voxtral Realtime** (Mistral AI) |
| AI Agents (routing, analysis, synthesis) | **Mistral Conversations API** with `web_search` tool |
| Agent models | `mistral-medium-latest` (configurable) |
| Workflow orchestration | **Temporal** (durable execution, retries, timeouts) |
| Media server | **MediaMTX** — SRT/RTMP/RTSP ingest |
| Backend (overlay + OBS) | **Laravel 12**, Inertia.js v2, Laravel Reverb |
| Frontend (overlay) | **Vue 3** + Tailwind CSS v4 |
| OBS integration | `obs-websocket-php` — scene switching via WebSocket |
| Persistence | **Laravel 12** (facts service) |
| Infrastructure | **Docker Compose** — PostgreSQL, Elasticsearch, Temporal |

## Repository Structure

```
.
├── ingestion/                   # Audio capture → real-time transcription
│   ├── realtime_transcript.py       # Mic → Voxtral STT → JSONL
│   └── requirements.txt
│
├── workflows/                   # Temporal workflows + Mistral AI agents
│   ├── debate_config.py             # Shared constants (task queue, timeouts)
│   ├── pyproject.toml               # Python deps (uv)
│   ├── workers/
│   │   ├── debate_worker.py                 # Temporal worker
│   │   └── debate_jsonl_to_temporal.py      # JSONL → Temporal starter
│   ├── workflows/
│   │   └── debate_workflow.py               # Workflow orchestration
│   ├── activities/
│   │   ├── debate_activities.py         # Fact-check business logic
│   │   ├── mistral_runtime.py           # Agent pool lifecycle + Conversations API
│   │   ├── agent_specs.py               # Agent definitions & tools
│   │   ├── prompts.py                   # Prompt templates + PoliticalProfile
│   │   └── schemas.py                   # Pydantic models for agent JSON outputs
│   └── utils/                           # Env loading, retry, text helpers
│
├── app/                         # Laravel — live overlay + OBS integration
│   ├── routes/
│   │   ├── api.php                  # POST /api/stream/fact-check
│   │   └── web.php                  # GET /overlays/fact-check (Inertia)
│   ├── app/
│   │   ├── Http/Controllers/        # StreamFactCheckController
│   │   ├── Events/                  # FactCheckContentUpdated (Reverb broadcast)
│   │   ├── Jobs/                    # VerifyFactCheckSceneTimestampJob
│   │   └── Services/Obs/            # OBS WebSocket integration
│   └── resources/js/
│       └── pages/overlays/fact-check/   # Vue overlay component
│
├── facts/                       # Laravel — fact persistence API
│   └── routes/api.php               # POST /api/facts
│
├── docker-compose.yml           # Full infrastructure stack
├── mediamtx.yml                 # MediaMTX config (SRT ingest)
├── dynamicconfig/               # Temporal dynamic configuration
├── scripts/                     # DB setup, namespace creation, mocks
└── cle.env.example              # Environment variable template
```

## Prerequisites

- **Docker** & **Docker Compose**
- **Python ≥ 3.14** with [uv](https://docs.astral.sh/uv/)
- **PHP ≥ 8.2** with Composer
- **Node.js** with pnpm
- A **Mistral AI API key**

## Quick Start

### 1. Clone & configure environment

```bash
git clone https://github.com/Barbapapazes/hackathon-paris.git
cd hackathon-paris

# Copy and fill in your API keys
cp cle.env.example .env
cp workflows/.env.example workflows/.env
# Edit both files — at minimum set MISTRAL_API_KEY
```

### 2. Start infrastructure (Temporal + PostgreSQL + Elasticsearch + MediaMTX)

```bash
docker compose up -d
```

This starts:

| Service | Port | Description |
|---|---|---|
| Temporal Server | `7233` | Workflow engine |
| Temporal UI | `8080` | Web dashboard |
| PostgreSQL | `5432` | Temporal persistence |
| Elasticsearch | `9200` | Temporal visibility |
| MediaMTX | `8890/udp` (SRT), `1935` (RTMP) | Media ingest |

### 3. Start the Laravel app (overlay + OBS)

```bash
cd app
composer install
cp .env.example .env
php artisan key:generate
php artisan migrate
pnpm install && pnpm run build

# In separate terminals:
php artisan serve            # http://localhost:8000
php artisan reverb:start     # WebSocket server
php artisan queue:listen     # Background jobs
```

The fact-check overlay is at `http://localhost:8000/overlays/fact-check` — point an OBS Browser Source to this URL.

### 4. Start the Temporal worker

```bash
cd workflows
uv sync
uv run python workers/debate_worker.py
```

### 5. Run the live pipeline

```bash
# Terminal 1 — Transcription → Temporal
cd ingestion
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python realtime_transcript.py \
  --input-device-index 0 \
  --personne "Candidate Name" \
  --source-video "TF1 20h" \
| tee debate_stream.jsonl \
| python ../workflows/workers/debate_jsonl_to_temporal.py --video-delay-seconds 30
```

Or submit an existing JSONL file:

```bash
cd workflows
uv run python workers/debate_jsonl_to_temporal.py \
  --input-jsonl ../debate_stream.jsonl \
  --video-delay-seconds 30
```

## How It Works

### 1. Transcription

`realtime_transcript.py` captures microphone audio via PyAudio, streams it to **Voxtral Realtime** (Mistral's speech-to-text), and emits one JSONL line per detected sentence:

```json
{
  "personne": "Valérie Pécresse",
  "question_posee": "",
  "affirmation": "Last 3 complete sentences merged",
  "affirmation_courante": "Latest single sentence",
  "metadata": {
    "source_video": "TF1 20h",
    "timestamp_elapsed": "12:45",
    "timestamp": "2026-02-28T17:12:34.123Z"
  }
}
```

### 2. Temporal Workflow

`debate_jsonl_to_temporal.py` ingests the JSONL stream and starts one **Temporal workflow** per sentence, passing:
- The current sentence (`current_json`)
- A sliding window of the last ~60 seconds of conversation (`last_minute_json`)
- The next sentence when available (`next_json`) for self-correction detection

The workflow (`debate_workflow.py`) orchestrates three activities in sequence:

1. **`analyze_debate_line`** — runs the full Mistral AI agent pipeline
2. **`check_next_phrase_self_correction`** — detects if the speaker corrects themselves
3. **`post_fact_check_result`** — POSTs the verdict to the Laravel app (after video delay)

### 3. Mistral AI Agent Pipeline

Six specialized agents are created on-the-fly via the Mistral Agents API:

| Agent | Role | Tools |
|---|---|---|
| **Routeur** | Classifies the claim, selects which specialists to run | — |
| **Statistique** | Verifies numeric claims against official sources | `web_search` |
| **Rhétorique** | Detects evasion of the journalist's question | — |
| **Cohérence** | Checks contradiction with past public statements | `web_search` |
| **Contexte** | Provides factual background context | `web_search` |
| **Éditeur** | Synthesizes all reports into a TV-ready verdict (2 sentences) | — |

All agents are executed via the **Conversations API** (`client.beta.conversations.start`), which handles tool execution server-side. Agents are created before each analysis and deleted afterward (guaranteed via `try/finally`).

### 4. Self-Correction Detection

Before posting a verdict, the system checks if the speaker's next sentence is a self-correction:

1. **Heuristic check** — keyword markers (e.g. "je me corrige", "en fait", "pardon") + number replacement patterns
2. **LLM fallback** — if the heuristic is inconclusive

If a self-correction is detected, the verdict is suppressed.

### 5. Live Overlay

The Laravel app receives the verdict via `POST /api/stream/fact-check`, broadcasts it through **Laravel Reverb** (WebSocket), and the Vue overlay component renders it in real time. The app also controls OBS scene switching via `obs-websocket-php` to show/hide the fact-check overlay on the live broadcast.

### 6. Verdict Format

```json
{
  "verdict_global": "Faux | Vrai | Exagéré | Trompeur | À nuancer | Contradictoire",
  "explications": {
    "statistique": { "texte": "...", "source": "INSEE", "url": "https://..." },
    "contexte":    { "texte": "...", "source": "Le Monde", "url": "https://..." },
    "rhetorique":  "Évasion détectée: ...",
    "coherence":   { "texte": "...", "source": "France Info", "url": "https://..." }
  },
  "sources": [
    { "organization": "INSEE", "url": "https://..." }
  ]
}
```

Only the relevant keys appear in `explications` depending on which agents were triggered by the router.


## Country Configuration

All prompts are parameterized by a **`PoliticalProfile`** dataclass (defined in `workflows/activities/prompts.py`). The default profile is `FRANCE_PROFILE` (French political TV debate).

To adapt the pipeline to another country:

```python
from activities.prompts import set_political_profile, PoliticalProfile

US_PROFILE = PoliticalProfile(
    country="United States",
    language="English",
    event_type="presidential debate",
    institutional_sources=["BLS", "CBO", "Census Bureau", "Federal Reserve"],
    trusted_media=["Associated Press", "Reuters", "NPR"],
    key_institutions=["White House", "Congress", "Supreme Court"],
    political_context_hint="Live US presidential debate. Prefer .gov sources.",
    correction_markers=["let me correct", "I misspoke", "I meant", "actually"],
)

set_political_profile(US_PROFILE)
```

| Field | Type | Description |
|---|---|---|
| `country` | `str` | Full country name |
| `language` | `str` | Primary language for agent output |
| `event_type` | `str` | Short label (e.g. "débat politique télévisé") |
| `institutional_sources` | `list[str]` | Preferred official data sources |
| `trusted_media` | `list[str]` | Reliable media outlets |
| `key_institutions` | `list[str]` | Government bodies the agents should know |
| `political_context_hint` | `str` | Free-form paragraph grounding the agents |
| `correction_markers` | `list[str]` | Language-specific self-correction phrases |

## Environment Variables

### `workflows/.env`

| Variable | Required | Default | Description |
|---|---|---|---|
| `MISTRAL_API_KEY` | **yes** | — | Mistral AI API key |
| `MISTRAL_AGENT_MODEL` | no | `mistral-medium-latest` | Model for all agents |
| `MISTRAL_AGENT_NAME_PREFIX` | no | `factcheck-live` | Agent name prefix on the platform |
| `FACT_CHECK_POST_URL` | no | `http://localhost:8000/api/stream/fact-check` | Endpoint to POST verdicts |
| `VIDEO_STREAM_DELAY_SECONDS` | no | `30` | Delay before posting (sync with live video) |
| `FACT_CHECK_ANALYSIS_TIMEOUT_SECONDS` | no | `30` | Activity timeout for analysis |
| `MISTRAL_RATE_LIMIT_MAX_RETRIES` | no | `4` | Max retries on rate-limit errors |
| `MISTRAL_RATE_LIMIT_BACKOFF_BASE_SECONDS` | no | `0.7` | Exponential backoff base |
| `MISTRAL_RATE_LIMIT_BACKOFF_MAX_SECONDS` | no | `6.0` | Backoff cap |

### `app/.env`

Standard Laravel environment plus:

| Variable | Description |
|---|---|
| `OBS_HOST` | OBS WebSocket host (default `127.0.0.1`) |
| `OBS_PORT` | OBS WebSocket port (default `4455`) |
| `OBS_PASSWORD` | OBS WebSocket password |
| `OBS_SCENE_FACT_CHECK` | OBS scene name for fact-check overlay |
| `OBS_SCENE_PROGRAM_DEFAULT` | Default OBS program scene |
| `OBS_COOLDOWN_SECONDS` | Min seconds between scene switches (default `5`) |
| `REVERB_*` | Laravel Reverb WebSocket configuration |

## Docker Compose Services

| Service | Image | Ports | Purpose |
|---|---|---|---|
| `mediamtx` | `bluenviron/mediamtx` | `8890/udp`, `1935`, `8554`, `8888` | SRT/RTMP/RTSP media ingest |
| `postgresql` | `postgres` | `5432` | Temporal persistence |
| `elasticsearch` | `elasticsearch` | `9200` | Temporal visibility store |
| `temporal` | `temporalio/server` | `7233` | Workflow engine |
| `temporal-ui` | `temporalio/ui` | `8080` | Temporal web dashboard |
| `temporal-admin-tools` | `temporalio/admin-tools` | — | DB schema setup |
| `app-web` | Custom (Laravel) | `8000` | Main app server |
| `app-queue` | Custom (Laravel) | — | Queue worker |
| `app-reverb` | Custom (Laravel) | `8081` | WebSocket server (Reverb) |

## Development

### Running tests

```bash
# Laravel app tests
cd app && php artisan test

# Facts service tests
cd facts && php artisan test
```

### Quick smoke test (no Temporal needed)

```bash
cd workflows/activities
uv run debate_activities.py
```

Creates fake data, runs the full agent pipeline, prints JSON results.

### Mock HTTP receiver

If the Laravel app isn't running:

```bash
python scripts/mock_fact_check_receiver.py --port 8000
```

## License

Private — Hackathon project.
