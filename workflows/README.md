# Workflows — Live Fact-Check Pipeline

Real-time fact-checking system that listens to a live debate transcript stream,
analyzes each sentence with specialized Mistral AI agents, and posts structured
verdicts to a downstream service. Orchestrated with **Temporal** for reliability.

## How It Works

```
                          ┌──────────────────────────────────┐
                          │        Live Audio Stream         │
                          └───────────────┬──────────────────┘
                                          │
                                          ▼
                          ┌──────────────────────────────────┐
                          │  realtime_transcript.py (STT)    │
                          │  Captures mic → sentences JSONL  │
                          └───────────────┬──────────────────┘
                                          │  stdout (JSONL)
                                          ▼
                          ┌──────────────────────────────────┐
                          │  debate_jsonl_to_temporal.py      │
                          │  Reads JSONL → starts 1 Temporal │
                          │  workflow per sentence            │
                          └───────────────┬──────────────────┘
                                          │
                       ┌──────────────────┼──────────────────┐
                       │       Temporal Server (durability)   │
                       └──────────────────┼──────────────────┘
                                          │
                                          ▼
                        ┌─────────────────────────────────────┐
                        │  debate_worker.py (Temporal Worker) │
                        │  Runs activities on each sentence   │
                        └────────────┬────────────────────────┘
                                     │
                    ┌────────────────┼────────────────────┐
                    ▼                ▼                    ▼
             ┌────────────┐  ┌────────────────┐  ┌──────────────┐
             │  analyze    │  │ self-correction│  │  post result │
             │  debate     │  │ check          │  │  to stream   │
             │  line       │  │                │  │  service     │
             └─────┬──────┘  └────────────────┘  └──────────────┘
                   │
                   ▼
    ┌──────────────────────────────────────────────────────┐
    │            Mistral AI Agent Pipeline                  │
    │                                                      │
    │  ┌─────────┐     ┌──────────────┐                    │
    │  │ Routeur  │────▶│ Decides which│                    │
    │  │ Agent    │     │ agents run   │                    │
    │  └─────────┘     └──────┬───────┘                    │
    │                         │                            │
    │       ┌────────┬────────┼─────────┬──────────┐       │
    │       ▼        ▼        ▼         ▼          │       │
    │  ┌────────┐┌────────┐┌────────┐┌──────────┐  │       │
    │  │  Stats ││Rhetoric││Coherenc││ Context  │  │       │
    │  │  Agent ││ Agent  ││  Agent ││  Agent   │  │       │
    │  │(search)││        ││(search)││ (search) │  │       │
    │  └───┬────┘└───┬────┘└───┬────┘└────┬─────┘  │       │
    │      └─────────┴─────────┴──────────┘        │       │
    │                     │                        │       │
    │                     ▼                        │       │
    │              ┌────────────┐                   │       │
    │              │  Editeur   │                   │       │
    │              │  Agent     │                   │       │
    │              │ (synthesis)│                   │       │
    │              └────────────┘                   │       │
    └──────────────────────────────────────────────┘       │
                          │                                │
                          ▼                                │
                  ┌───────────────┐                        │
                  │ JSON verdict  │────────────────────────┘
                  │ + sources     │
                  └───────────────┘
```

### Pipeline Steps

1. **Transcription** — `realtime_transcript.py` captures live audio and emits
   one JSONL line per detected sentence (speaker, claim, timestamp).

2. **Ingestion** — `debate_jsonl_to_temporal.py` reads the JSONL stream
   (file or stdin) and starts one Temporal workflow per sentence with context
   from the last ~60 seconds of conversation.

3. **Temporal Workflow** (`debate_workflow.py`) orchestrates four explicit steps,
   each in its own method with a dedicated retry policy:

   | Step | Activity / action | Retry policy |
   |------|-------------------|--------------|
   | 1 | `analyze_debate_line` — full Mistral AI pipeline | up to 3 attempts, exp. backoff (2 s → 20 s) |
   | 2 | `check_next_phrase_self_correction` — detect speaker self-correction | up to 2 attempts; failure defaults to *no correction* |
   | 3 | `(sleep)` wait remaining video-sync delay | n/a |
   | 4 | `post_fact_check_result` — HTTP POST verdict | up to 5 attempts, exp. backoff (2 s → 30 s) |

   **Resilience notes**
   - If the self-correction check fails (all retries exhausted), the workflow
     defaults to *"no correction detected"* and still posts the verdict, so a
     transient network error never silently suppresses a valid fact-check.
   - If the post activity fails after all retries, Temporal raises the error
     and the workflow execution is marked as failed — observable in the UI.
   - Activity logic is split into focused private helpers (`_run_analysis`,
     `_run_self_correction_check`, `_wait_remaining_delay`, `_should_skip_post`,
     `_annotate_skipped`, `_post_result`, `_build_output`) so each concern can
     be read, tested, and modified independently.

4. **Analysis** (`debate_activities.py`) runs Mistral AI agents:
   - **Routeur** — classifies the claim and selects which specialist agents to run
   - **Statistique** — verifies numeric claims via `web_search`
   - **Rhétorique** — detects evasion of the journalist's question
   - **Cohérence** — checks contradiction with past public statements via `web_search`
   - **Contexte** — provides factual background context via `web_search`
   - **Éditeur** — synthesizes all reports into a TV-ready verdict (2 sentences)

5. **Self-Correction** — heuristic first (keyword markers + number replacement),
   then LLM fallback. If the next sentence corrects the current one, the verdict
   is suppressed.

### Agent Architecture

Each agent is a **Mistral platform agent** created via the Agents API
(`client.beta.agents.create`). Agents with `web_search` tools are executed via
the **Conversations API** (`client.beta.conversations.start`), which handles
tool execution server-side and returns a structured JSON response.

#### Workflow-driven prompts

Agents with `web_search` (statistique, cohérence, contexte) embed an explicit
`<workflow>` section in their system prompt that enforces a three-phase loop:

```
<workflow>
## 1. Search (MANDATORY — never skip)
   Call web_search at least once. Refine and search again if results are weak.

## 2. Analyse
   Review results. Extract figures, dates, contradictions, and context.

## 3. Write output
   Produce the structured JSON. Do NOT copy URLs — they are extracted
   automatically from tool-call results by the downstream system.
</workflow>
```

This pattern guarantees that the model always performs at least one `web_search`
call before writing its report, rather than generating an output from training
data alone. The Conversations API loop (tool call → tool result → model output)
runs server-side until the model reaches its final answer.

The **Éditeur** agent receives the full raw text of all specialist reports and
synthesizes a final verdict. It is explicitly instructed *not* to reproduce or
invent URLs — source links are harvested automatically from every specialist
agent's tool-call results via `extract_sources_from_conversation` in
`mistral_runtime.py`, then attached to the final output by the downstream system.

```
 debate_activities.py
 ────────────────────
        │
        │  create_agent_pool(keys=[...])
        │  ─────────────────────────────
        │  Creates one Mistral agent per specialist key.
        │  Each agent has: model, instructions (with <workflow>), tools, response_format.
        │
        │  run_task(specialist_key, prompt)
        │  ────────────────────────────────
        │  Calls the specialist directly via conversations.start().
        │  No supervisor/handoff layer — routing is done in Python.
        │
        ▼
 ┌──────────────────────────────────────────────────┐
 │  Mistral Conversations API (agentic loop)         │
 │                                                  │
 │  prompt ──▶ model ──▶ web_search call            │
 │                  ◀── search results              │
 │             model ──▶ (optional) more searches   │
 │                  ◀── results                     │
 │             model ──▶ final JSON output          │
 │                                                  │
 │  Sources extracted from tool-call outputs        │
 │  by extract_sources_from_conversation()          │
 └──────────────────────────────────────────────────┘
```

---

## Political Profile (Country Configuration)

All prompts are parameterised by a **`PoliticalProfile`** dataclass defined in
`activities/prompts.py`. The profile injects country-specific context into every
agent prompt: preferred institutional sources, trusted media, key institutions,
correction markers, and a free-form political context hint.

The default profile is **`FRANCE_PROFILE`** (French political TV debate). To
adapt the pipeline to a different country:

### Option A — Swap at import time

```python
from activities.prompts import set_political_profile, PoliticalProfile

US_PROFILE = PoliticalProfile(
    country="United States",
    language="English",
    event_type="presidential debate",
    institutional_sources=[
        "Bureau of Labor Statistics (BLS)",
        "Congressional Budget Office (CBO)",
        "Census Bureau",
        "Federal Reserve",
    ],
    trusted_media=[
        "Associated Press", "Reuters", "NPR",
        "The New York Times", "The Washington Post",
    ],
    key_institutions=[
        "White House", "Congress", "Supreme Court",
        "Federal Reserve", "Department of Justice",
    ],
    political_context_hint=(
        "This is a live US presidential debate. Claims often reference federal "
        "legislation, executive orders, GDP, unemployment rates, and healthcare "
        "policy. Prefer .gov and major wire-service sources."
    ),
    correction_markers=[
        "let me correct",
        "I misspoke",
        "I meant",
        "actually",
        "correction",
        "no, rather",
    ],
)

set_political_profile(US_PROFILE)
```

### Option B — Extend `FRANCE_PROFILE` fields

The `FRANCE_PROFILE` is a frozen dataclass. Use `dataclasses.replace()` to
create a variant:

```python
from dataclasses import replace
from activities.prompts import FRANCE_PROFILE, set_political_profile

my_profile = replace(FRANCE_PROFILE, political_context_hint="Élection présidentielle 2027.")
set_political_profile(my_profile)
```

### Profile Fields

| Field | Type | Description |
|---|---|---|
| `country` | `str` | Full country name |
| `language` | `str` | Primary language for agent output |
| `event_type` | `str` | Short label for the event (e.g. "débat politique télévisé") |
| `institutional_sources` | `list[str]` | Preferred official data sources |
| `trusted_media` | `list[str]` | Reliable media outlets |
| `key_institutions` | `list[str]` | Government bodies agents should know |
| `political_context_hint` | `str` | Free-form paragraph grounding the agents |
| `correction_markers` | `list[str]` | Language-specific self-correction phrases |

---

## Project Structure

```
workflows/
├── debate_config.py              # Shared constants (task queue, timeouts)
├── .env                          # Local environment variables (git-ignored)
├── .env.example                  # Template for .env
├── pyproject.toml                # Python project (uv)
│
├── workers/
│   ├── debate_worker.py          # Temporal worker (registers workflow + activities)
│   └── debate_jsonl_to_temporal.py  # JSONL reader → Temporal workflow starter
│
├── workflows/
│   └── debate_workflow.py        # Temporal workflow orchestration
│
├── activities/
│   ├── debate_activities.py      # Business logic: fact-check activities
│   ├── mistral_runtime.py        # Agent pool lifecycle + Conversations API calls
│   ├── agent_specs.py            # Agent definitions (instructions, tools, schemas)
│   ├── prompts.py                # Prompt templates + PoliticalProfile (country config)
│   └── schemas.py                # Pydantic models for agent JSON outputs
│
└── utils/
    ├── env.py                    # Loads workflows/.env
    ├── text.py                   # Extract affirmation from payloads
    ├── retry.py                  # Rate-limit detection + exponential backoff
    └── sources.py                # URL validation + domain normalization
```

---

## Environment Variables

This sub-project uses its own `workflows/.env` file (not the repo root).
`utils/env.py` loads it with override enabled, so `.env` values take precedence
over shell environment.

Copy `.env.example` to `.env` and fill in your key:

```bash
cp .env.example .env
```

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MISTRAL_API_KEY` | **yes** | — | Mistral API key |
| `MISTRAL_AGENT_MODEL` | no | `mistral-medium-latest` | Model used for all agents |
| `MISTRAL_AGENT_NAME_PREFIX` | no | `factcheck-live` | Agent name prefix on the platform |
| `FACT_CHECK_POST_URL` | no | `http://localhost:8000/api/stream/fact-check` | Endpoint to POST verdicts |
| `VIDEO_STREAM_DELAY_SECONDS` | no | `30` | Delay before posting (sync with live video) |
| `FACT_CHECK_ANALYSIS_TIMEOUT_SECONDS` | no | `30` | Temporal activity timeout for analysis |
| `MISTRAL_RATE_LIMIT_MAX_RETRIES` | no | `4` | Max retries on rate-limit errors |
| `MISTRAL_RATE_LIMIT_BACKOFF_BASE_SECONDS` | no | `0.7` | Base backoff (exponential) |
| `MISTRAL_RATE_LIMIT_BACKOFF_MAX_SECONDS` | no | `6.0` | Max backoff cap |

---

## Run

### Prerequisites

- Python >= 3.14 with [uv](https://docs.astral.sh/uv/) installed
- A [Temporal](https://temporal.io) server (dev mode or cloud)
- A valid `MISTRAL_API_KEY`

### 1) Start Temporal (dev mode)

```bash
temporal server start-dev --db-filename temporal.db --ui-port 8233
```

Temporal UI will be available at `http://localhost:8233`.

### 2) (Optional) Mock HTTP receiver

If you don't have the real stream service running:

```bash
cd ..
source ingestion/.venv/bin/activate
python scripts/mock_fact_check_receiver.py --port 8000
```

### 3) Start the Temporal worker

```bash
cd workflows
uv run python workers/debate_worker.py
```

The worker connects to Temporal on `localhost:7233` and listens on the
`debate-json-task-queue` task queue.

### 4) Submit a JSONL file

```bash
cd workflows
uv run python workers/debate_jsonl_to_temporal.py \
  --input-jsonl ../debate_stream.jsonl \
  --video-delay-seconds 30
```

### 5) Live end-to-end (mic → fact-check → post)

```bash
cd ..
source ingestion/.venv/bin/activate
python ingestion/realtime_transcript.py \
  --input-device-index 0 \
  --personne "Valérie Pécresse" \
  --source-video "TF1 20h" \
  --question-posee "" \
| tee debate_stream.jsonl \
| python workflows/workers/debate_jsonl_to_temporal.py --video-delay-seconds 30
```

### 6) Quick smoke test (no Temporal)

Run the built-in demo directly to verify agent calls work:

```bash
cd workflows/activities
uv run debate_activities.py
```

This creates fake data, calls `analyze_debate_line` and
`check_next_phrase_self_correction`, and prints JSON results.

---

## JSONL Input Format

Each line is a JSON object with these fields:

```json
{
  "personne": "Speaker Name",
  "question_posee": "Journalist question (optional)",
  "affirmation": "The sentence to fact-check.",
  "timestamp": "2026-03-01T20:15:30Z"
}
```

The `debate_jsonl_to_temporal.py` script automatically maintains a sliding
window of the last ~60 seconds of conversation as context
(`previous_phrases` / `last_minute_json`).

---

## Output Format

The final verdict posted to `FACT_CHECK_POST_URL`:

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

Only relevant keys appear in `explications` depending on which agents were
triggered by the router.

---

## Notes

- **Temporal activity names** remain unchanged (`analyze_debate_line`,
  `check_next_phrase_self_correction`, `post_fact_check_result`) to avoid
  breaking running workflow contracts.
- The workflow **waits** for the remaining video delay after analysis completes
  before posting, so verdicts are synchronized with the live broadcast.
- If the next sentence is detected as a **self-correction**, the post is skipped
  to avoid publishing a verdict on something the speaker already retracted.
- Agent cleanup is guaranteed via `try/finally` — all Mistral platform agents
  are deleted after each activity execution.
- **`PoliticalProfile`** is a frozen dataclass — use `set_political_profile()`
  or `dataclasses.replace()` to adapt the pipeline to another country. All
  prompts, source preferences, and correction markers automatically adapt.
