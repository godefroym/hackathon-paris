#!/usr/bin/env python3
from __future__ import annotations
import os


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}

DEFAULT_TASK_QUEUE = "debate-json-task-queue"
WORKFLOW_TYPE = "DebateJsonNoopWorkflow"

# Project-level knobs for stream synchronization and workflow timing.
DEFAULT_VIDEO_DELAY_SECONDS = 30.0
DEFAULT_ANALYSIS_TIMEOUT_SECONDS = 30
DEFAULT_POST_TIMEOUT_SECONDS = 10
FACT_CHECK_EMERGENCY_DEGRADED_MODE = _env_flag(
    "FACT_CHECK_EMERGENCY_DEGRADED_MODE", False
)
DEFAULT_ANALYZE_ACTIVITY_MAX_ATTEMPTS = max(
    1,
    int(os.getenv("FACT_CHECK_ANALYZE_ACTIVITY_MAX_ATTEMPTS", "1")),
)
