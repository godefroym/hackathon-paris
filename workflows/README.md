# Workflows

## Debate analysis workflow (integration test)

This folder contains the Temporal wiring for the real-time transcript pipeline:

- `debate_workflow.py`: receives two JSON payloads and calls `analyze_debate_line`.
- `debate_worker.py`: worker for task queue `debate-json-task-queue`, registers
  `analyze_debate_line` from `activities.py`.
- `debate_jsonl_to_temporal.py`: reads JSONL (file or stdin) and starts one
  workflow per line.
- `activities.py`: The core "Brain" of the system. Uses a multi-agent `AgentPool` (Mistral Agents API) with specialized experts and a quality-control `Judge` agent.

For each transcript line, the launcher sends:
- `current_json`: the original JSON line.
- `last_minute_json`: aggregate built from payload timestamps, containing all
  phrases from the last 60 seconds.

Per-line post delay is computed as:
- `computed_post_delay = VIDEO_STREAM_DELAY_SECONDS - (ts_current - ts_previous)`
- clamped to `>= 0`
- first line uses full `VIDEO_STREAM_DELAY_SECONDS`

POST payload sent by the workflow:
- `workflow_result` only (result returned by `analyze_debate_line`)

Main timing variables (in `cle.env` or CLI):
- `VIDEO_STREAM_DELAY_SECONDS` (default: 30)
- `FACT_CHECK_ANALYSIS_TIMEOUT_SECONDS` (default: 30)

### Run

Start the full stack (Temporal + app API + workflow worker) with Docker:

```bash
cd ..
./scripts/run_stack.sh up
```

The stack now includes namespace creation (`temporal-create-namespace`) before
starting `workflows-worker`.

Create `cle.env` at repo root (required by `activities.py`):

```bash
cd ..
cp cle.env.example cle.env
# puis remplir MISTRAL_API_KEY, FACT_CHECK_POST_URL
# MISTRAL_WEB_SEARCH_MODEL, VIDEO_STREAM_DELAY_SECONDS et FACT_CHECK_ANALYSIS_TIMEOUT_SECONDS sont optionnels
```

Optional: start a local mock receiver for POST validation (outside Docker):

```bash
cd ..
source ingestion/.venv/bin/activate
python scripts/mock_fact_check_receiver.py --port 8000
```

Submit JSON lines from a file:

```bash
cd workflows
python debate_jsonl_to_temporal.py --input-jsonl ../debate_stream.jsonl --video-delay-seconds 30
```

Submit JSON lines from a live stream:

```bash
cd ..
source ingestion/.venv/bin/activate
python ingestion/realtime_transcript.py \
  --input-device-index 0 \
  --personne "Valérie Pécresse" \
  --source-video "TF1 20h" \
  --question-posee "" \
| tee debate_stream.jsonl \
| docker compose run --rm -T workflows-launcher \
    python workflows/debate_jsonl_to_temporal.py --address temporal:7233 --input-jsonl - --video-delay-seconds 30
```

To stop everything:

```bash
./scripts/run_stack.sh down
```

Useful commands:

```bash
./scripts/run_stack.sh ps
./scripts/run_stack.sh logs workflows-worker
```
