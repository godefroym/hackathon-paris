#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PATH="$ROOT_DIR/ingestion/.venv/bin/activate"
if [[ ! -f "$VENV_PATH" ]]; then
  VENV_PATH="$ROOT_DIR/.venv/bin/activate"
fi
VIDEO_DELAY_SECONDS="${VIDEO_DELAY_SECONDS:-30}"
MAX_WAIT_NEXT_PHRASE_SECONDS="${MAX_WAIT_NEXT_PHRASE_SECONDS:-1.0}"
ANALYSIS_TIMEOUT_SECONDS="${ANALYSIS_TIMEOUT_SECONDS:-90}"
PIPELINE_LANGUAGE="${PIPELINE_LANGUAGE:-fr}"
TEE_JSONL_PATH="${TEE_JSONL_PATH:-}"

cd "$ROOT_DIR"

if [[ ! -f "$VENV_PATH" ]]; then
  echo "Missing venv activation file: $VENV_PATH" >&2
  echo "Create it first: cd $ROOT_DIR/ingestion && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && pip install -r ../texte/requirements.txt" >&2
  exit 1
fi

source "$VENV_PATH"

if [[ -n "$TEE_JSONL_PATH" ]]; then
  python texte/realtime_transcript_fusion.py "$@" --providers mistral --pipeline-language "$PIPELINE_LANGUAGE" \
    | tee "$TEE_JSONL_PATH" \
    | docker compose run --rm -T workflows-launcher \
        python workflows/debate_jsonl_to_temporal.py \
          --address temporal:7233 \
          --input-jsonl - \
          --video-delay-seconds "$VIDEO_DELAY_SECONDS" \
          --analysis-timeout-seconds "$ANALYSIS_TIMEOUT_SECONDS" \
          --max-wait-next-phrase-seconds "$MAX_WAIT_NEXT_PHRASE_SECONDS"
else
  python texte/realtime_transcript_fusion.py "$@" --providers mistral --pipeline-language "$PIPELINE_LANGUAGE" \
    | docker compose run --rm -T workflows-launcher \
        python workflows/debate_jsonl_to_temporal.py \
          --address temporal:7233 \
          --input-jsonl - \
          --video-delay-seconds "$VIDEO_DELAY_SECONDS" \
          --analysis-timeout-seconds "$ANALYSIS_TIMEOUT_SECONDS" \
          --max-wait-next-phrase-seconds "$MAX_WAIT_NEXT_PHRASE_SECONDS"
fi
