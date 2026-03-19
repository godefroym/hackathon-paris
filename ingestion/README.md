# /ingestion ⚙️

Cœur technique du pipeline Veristral.

## 🚀 Scripts principaux

*   `realtime_transcript.py` : Capture l'audio, se connecte à l'API Mistral Realtime et gère les WebSockets (OBS).
*   `fact_check_pipeline.py` : Orchestrateur qui lit le flux JSONL et coordonne le travail des agents.
*   `session_logger.py` : Utilitaire de journalisation formatant les sorties en Markdown pour le rapport AFP.

## 📡 Flux de données

```
Micro/SRT -> realtime_transcript.py -> [Pipe JSONL] -> fact_check_pipeline.py -> Rapport / OBS
```
