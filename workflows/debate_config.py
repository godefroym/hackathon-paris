#!/usr/bin/env python3
from __future__ import annotations

DEFAULT_TASK_QUEUE = "debate-json-task-queue"
WORKFLOW_TYPE = "DebateJsonNoopWorkflow"

# Project-level knobs for stream synchronization and workflow timing.
DEFAULT_VIDEO_DELAY_SECONDS = 30.0
DEFAULT_ANALYSIS_TIMEOUT_SECONDS = 30
DEFAULT_POST_TIMEOUT_SECONDS = 10
