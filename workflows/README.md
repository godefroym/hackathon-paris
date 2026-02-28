# Workflows

## Debate no-op workflow (integration test)

This folder now contains a placeholder Temporal workflow used to validate the
real-time transcript pipeline:

- `debate_workflow.py`: receives two JSON payloads and sleeps for 30s by default.
- `debate_worker.py`: worker for task queue `debate-json-task-queue`.
- `debate_jsonl_to_temporal.py`: reads JSONL (file or stdin) and starts one
  workflow per line.

For each transcript line, the launcher sends:
- `current_json`: the original JSON line.
- `last_minute_json`: aggregate built from payload timestamps, containing all
  phrases from the last 60 seconds.

### Run

Start Temporal dev server first:

```bash
temporal server start-dev --db-filename temporal.db --ui-port 8233
```

Then start the worker:

```bash
cd workflows
uv run python debate_worker.py
```

Submit JSON lines from a file:

```bash
cd workflows
uv run python debate_jsonl_to_temporal.py --input-jsonl ../debate_stream.jsonl --noop-seconds 30
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
| python workflows/debate_jsonl_to_temporal.py --noop-seconds 30
```
