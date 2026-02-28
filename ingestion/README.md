# Ingestion (realtime transcript)

`realtime_transcript.py` captures microphone audio, sends it to Mistral realtime
transcription (dual-delay), and emits one JSON object per complete sentence.

Output schema:

```json
{
  "personne": "Valérie Pécresse",
  "question_posee": "",
  "affirmation": "Dernieres phrases completes fusionnees",
  "affirmation_courante": "Derniere phrase complete",
  "metadata": {
    "source_video": "TF1 20h",
    "timestamp_elapsed": "12:45",
    "timestamp": "2026-02-28T17:12:34.123Z"
  }
}
```

By default, `affirmation` merges the 3 latest complete sentences.
`metadata.timestamp` is now precise (UTC ISO with milliseconds).

## Install

```bash
cd ingestion
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
source .venv/bin/activate
export MISTRAL_API_KEY="your_key"
python realtime_transcript.py --list-devices
python realtime_transcript.py --input-device-index 0 --personne "Valérie Pécresse" --source-video "TF1 20h"
```
