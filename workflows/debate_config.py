#!/usr/bin/env python3
from __future__ import annotations

DEFAULT_TASK_QUEUE = "debate-json-task-queue"
WORKFLOW_TYPE = "DebateJsonNoopWorkflow"

# ── Transcript batch (STT → claim extraction → child fact-check) ──────────────
TRANSCRIPT_TASK_QUEUE = "transcript-batch-task-queue"
TRANSCRIPT_WORKFLOW_TYPE = "TranscriptBatchWorkflow"

# How many seconds of speech to accumulate before flushing to a batch workflow.
DEFAULT_STT_BUFFER_SECONDS = 20.0
# Minimum number of complete sentences before triggering a flush (even if timer
# hasn't fired yet). They are OR-combined: whichever condition fires first wins.
DEFAULT_STT_MIN_SENTENCES = 6
# Maximum number of claims to fan-out per batch window (guard against model
# over-extraction; the extractor is instructed to be selective anyway).
MAX_CLAIMS_PER_BATCH = 5

# Project-level knobs for stream synchronization and workflow timing.
DEFAULT_VIDEO_DELAY_SECONDS = 45.0
DEFAULT_ANALYSIS_TIMEOUT_SECONDS = 30
DEFAULT_POST_TIMEOUT_SECONDS = 10

# Timeout for the claim-extraction activity (fast model, no web search).
DEFAULT_EXTRACTION_TIMEOUT_SECONDS = 20

# obs-controller — main stream overlay endpoint.  Override via FACT_CHECK_POST_URL env var.
DEFAULT_FACT_CHECK_POST_URL = "http://localhost:8001/api/stream/fact-check"

# obs-veristral — secondary endpoint (Veristral display).  Override via VERISTRAL_POST_URL.
DEFAULT_VERISTRAL_POST_URL = "http://localhost:8002/api/facts"

# ── Next-sentence signal ───────────────────────────────────────────────────────
# Signal name sent by the ingestion layer to DebateJsonNoopWorkflow once the
# next speech sentences are available.  The signal payload carries the
# speaker's subsequent content so the reviewer agent can decide whether a
# self-correction occurred and what tone to adopt.
NEXT_SENTENCE_SIGNAL = "next_sentence"

# Minimum time (seconds) the workflow waits for the next_sentence signal even
# if the analysis already consumed most of the video delay budget.
DEFAULT_SIGNAL_WAIT_MIN_SECONDS = 5
