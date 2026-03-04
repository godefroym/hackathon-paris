# Ingestion

Handles the real-time capture of audio and transcription using Mistral AI's Voxtral model.

## Main Components
- `realtime_transcript.py`: The core script that captures audio from a microphone/virtual input and streams it to Mistral's transcription API.
- `requirements.txt`: Python dependencies specific to the ingestion module.

## Usage
Typically used by piping its output to the Temporal launcher:
```bash
python ingestion/realtime_transcript.py | python workflows/debate_jsonl_to_temporal.py
```
