# Veristral - Mistral AI Hackathon 2026
Building a democratic "War Room" to combat the asymmetry of disinformation through real-time, AI-powered fact-checking.

## Overview
In modern political debates, false information spreads significantly faster than the truth. Vériscope solves the "latency of truth" by providing a live analysis engine capable of sourcing and contextualizing political discourse with less than 10 seconds of latency.

## Technical Stack
- **Transcription (STT)**: Voxtral-realtime-latest (Mistral AI).
- **Orchestration**: Temporal for resilient workflow management.
- **Reasoning Models**: 
  - **Router**: Mistral-Small-latest for classification.
  - **Expert Analysis**: Mistral-Large-latest for complex reasoning.
  - **Quality Control**: A dedicated "Judge" agent validates expert outputs.
- **Knowledge Retrieval**: Mistral Web Search API (filtered for institutional sources like INSEE, gouv.fr).
- **Broadcast Integration**: OBS WebSockets.

## Repository Structure
- `ingestion/`: Audio capture and Voxtral realtime transcription logic.
- `workflows/`: Temporal worker and activities (the "Brain" of the system).
- `apps/obs-controller`: Laravel-based bridge to OBS.
- `scripts/`: Environment setup and database validation.
- `trash/`: Archive of research notebooks and legacy scripts.

## Getting Started
1. **Environment**: Copy `cle.env.example` to `cle.env` and fill in your `MISTRAL_API_KEY`.
2. **Dependencies**: `pip install -r requirements.txt` (using `venv_hackathon`).
3. **Run Worker**: `python workflows/debate_worker.py`
4. **Test Individually**: Use `python test_agents.py` to test a single JSON phrase without the full stream.

---
Developed during the Mistral AI Hackathon 2026.
