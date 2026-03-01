
Gemini a dit
# Veristral - Mistral AI Hackathon 2026
Building a democratic "War Room" to combat the asymmetry of disinformation through real-time, AI-powered fact-checking.

# Overview
In modern political debates, false information spreads significantly faster than the truth. Vériscope solves the "latency of truth" by providing a live analysis engine capable of sourcing and contextualizing political discourse with less than 10 seconds of latency.

Our system doesn't just check facts; it bridges the gap between televised speech and factual reality, ensuring that the correction reaches the viewer at the exact moment the claim is made.

# Technical Stack
Transcription (STT): Voxtral-realtime-latest (Mistral AI) for ultra-low latency audio-to-text.

Orchestration: Temporal for resilient workflow management and task queuing.

Reasoning Models: * Router: Mistral-Small-latest (Minitral) for rapid classification.

Expert Analysis: Mistral-Large-latest for complex reasoning and final synthesis.

Monitoring: Weights & Biases (Weave) for prompt tracking and evaluation.

Knowledge Retrieval: Google Search API (filtered for institutional sources) + RAG (Retrieval-Augmented Generation).

Broadcast Integration: OBS-websocket for automated live-on-screen alerts.

# Architecture & Workflow
The project is built on a Producer/Consumer architecture designed for massive parallelism.

Ingestion & Buffer: Captures raw audio via a virtual mic, managing a 20s sliding window to ensure no context is lost.

The "Brain" (Multi-Agent System): * Minitral acts as the dispatcher, filtering duplicates and routing claims.

Parallel Experts (Statistical, Rhetorical, Consistency, Context) execute simultaneously using asyncio.gather().

Synthesis & Action: Mistral Large aggregates expert reports into a "punchy" verdict and triggers an OBS scene change via WebSocket.

# Repository Structure
Based on our sprint organization:

ingestion/: Audio capture and Voxtral realtime transcription logic.

analysis/: Agentic workflows, prompt engineering, and Mistral model routing.

workflows/: Temporal worker definitions and resilient processing logic.

apps/obs-controller: Integration scripts to communicate with OBS.

frontend/: React/Streamlit dashboard for the "Citizen War Room" UI.

# Data Contract
All modules communicate via a standardized JSON interface:

JSON
{
  "id": "uuid",
  "timestamp": "HH:MM:SS",
  "category": "STAT | RHETORIC | CONTEXT | CONTRADICTION",
  "raw_input": "The political statement",
  "analysis": {
    "verdict": "green | orange | red | blue",
    "title": "Short Verdict Title",
    "explanation": "Pedagogical breakdown by Mistral Large",
    "source_url": "Link to evidence",
    "confidence_score": 0.95
  }
}
🚀 Getting Started
Environment: Copy .env.example to .env and fill in your Mistral and Temporal credentials.

Infrastructure: Run docker-compose up to start the Temporal server and MediaMTX stack.

Run Ingestion: python ingestion/realtime_transcript.py

Run Worker: python workflows/debate_worker.py

Developed during the Mistral AI Hackathon 2026. We don't change politics; we change the transparency of the debate.
