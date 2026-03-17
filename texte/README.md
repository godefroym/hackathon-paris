# ElevenLabs realtime transcription scripts

This folder provides realtime STT scripts (ElevenLabs and fusion mode) that
output the same JSON schema used by your existing Temporal pipeline.

## Files

- `realtime_transcript_elevenlabs.py`
  - microphone -> ElevenLabs realtime websocket -> JSONL output
- `run_elevenlabs_to_temporal.sh`
  - wrapper to stream JSONL directly into Temporal launcher
- `realtime_transcript_fusion.py`
  - microphone -> Mistral + ElevenLabs in parallel -> sentence arbitration -> JSONL output
- `run_fusion_to_temporal.sh`
  - wrapper to stream fused JSONL directly into Temporal launcher
- `requirements.txt`
  - Python deps for this folder

## JSON output schema (one line per committed phrase)

```json
{
  "personne": "Valerie Pecresse",
  "question_posee": "",
  "affirmation": "Last N committed phrases",
  "affirmation_courante": "Latest committed phrase",
  "metadata": {
    "source_video": "TF1 20h",
    "timestamp_elapsed": "12:45",
    "timestamp_start": "2026-03-01T10:01:58.123Z",
    "timestamp_end": "2026-03-01T10:02:03.456Z",
    "timestamp": "2026-03-01T10:02:03.456Z"
  }
}
```

`affirmation` keeps a sliding window of the latest complete phrases (`--recent-window`, default `3`).
`metadata.timestamp_start` is the estimated phrase start used by the Temporal launcher
to keep post timing close to `VIDEO_DELAY_SECONDS` from speech start.

## Install

```bash
cd /Users/godefroy.meynard/Documents/test_datagouv_mcp/hackaton_audio/hackathon-paris/ingestion
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r ../texte/requirements.txt
```

## Keys

These scripts auto-load `/Users/godefroy.meynard/Documents/test_datagouv_mcp/hackaton_audio/hackathon-paris/cle.env`.
Add your keys there:

```bash
MISTRAL_API_KEY=...
ELEVENLABS_API_KEY=...
```

## Realtime STT only

```bash
cd /Users/godefroy.meynard/Documents/test_datagouv_mcp/hackaton_audio/hackathon-paris
source ingestion/.venv/bin/activate

python texte/realtime_transcript_elevenlabs.py --list-devices

python texte/realtime_transcript_elevenlabs.py \
  --input-device-index 0 \
  --personne "Valerie Pecresse" \
  --source-video "TF1 20h" \
  --question-posee "" \
  --recent-window 3
```

Default is multilingual auto-detection (`--language-mode auto`).
To force one language:

```bash
python texte/realtime_transcript_elevenlabs.py \
  --input-device-index 0 \
  --personne "Valerie Pecresse" \
  --source-video "TF1 20h" \
  --language-mode fixed \
  --language-code en
```

## Realtime STT + Temporal launcher (single command)

```bash
cd /Users/godefroy.meynard/Documents/test_datagouv_mcp/hackaton_audio/hackathon-paris
export VIDEO_DELAY_SECONDS=30
export MAX_WAIT_NEXT_PHRASE_SECONDS=0.5
export ANALYSIS_TIMEOUT_SECONDS=20
# optional
export TEE_JSONL_PATH=debate_stream_elevenlabs.jsonl

./texte/run_elevenlabs_to_temporal.sh \
  --input-device-index 0 \
  --personne "Valerie Pecresse" \
  --source-video "TF1 20h" \
  --question-posee ""
```

## Realtime STT fusion (Mistral only)

```bash
cd /Users/godefroy.meynard/Documents/test_datagouv_mcp/hackaton_audio/hackathon-paris
source ingestion/.venv/bin/activate

python texte/realtime_transcript_fusion.py --list-devices

python texte/realtime_transcript_fusion.py \
  --input-device-index 0 \
  --personne "Valerie Pecresse" \
  --source-video "TF1 20h" \
  --question-posee "" \
  --language-mode fixed \
  --language-code fr \
  --preferred-provider mistral \
  --cleanup-mode aggressive \
  --show-decisions
```

Provider behavior:
- ElevenLabs is disabled in the fusion pipeline for stability.
- The script always emits the Mistral transcript stream (same JSON schema and Temporal wiring).

Main knobs:
- `--disable-llm-judge` to force heuristic-only mode.
- `--judge-model mistral-small-latest` to change arbitration model.
- `--pair-max-skew-seconds`, `--pair-min-similarity`, and `--solo-wait-seconds` to tune matching/timeout.
- `--dedupe-window-seconds` to avoid duplicate emitted sentences.
- `--preferred-provider mistral` to bias unresolved cases toward Mistral.
- `--cleanup-mode conservative|aggressive|none` to post-clean final emitted sentence.
  - `conservative` now blocks entity/number substitutions (e.g. country or person swap).

## Realtime fusion + Temporal launcher (single command)

```bash
cd /Users/godefroy.meynard/Documents/test_datagouv_mcp/hackaton_audio/hackathon-paris
export VIDEO_DELAY_SECONDS=30
export MAX_WAIT_NEXT_PHRASE_SECONDS=0.5
export ANALYSIS_TIMEOUT_SECONDS=20
# optional
export TEE_JSONL_PATH=debate_stream_fusion.jsonl

./texte/run_fusion_to_temporal.sh \
  --input-device-index 0 \
  --personne "Valerie Pecresse" \
  --source-video "TF1 20h" \
  --question-posee ""
```

## Notes

- Default mode is `--commit-strategy vad` for phrase-level commits.
- Default language mode is `--language-mode auto` (multi-language).
- Use `--show-partials` if you want partial transcript logs in stderr.
- `run_fusion_to_temporal.sh` forces `--providers mistral`.
