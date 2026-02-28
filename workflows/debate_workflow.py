#!/usr/bin/env python3
from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow

DEFAULT_TASK_QUEUE = "debate-json-task-queue"
WORKFLOW_TYPE = "DebateJsonNoopWorkflow"
DEFAULT_NOOP_SECONDS = 30


@workflow.defn(name=WORKFLOW_TYPE)
class DebateJsonNoopWorkflow:
    @workflow.run
    async def run(
        self,
        current_json: dict[str, Any],
        last_minute_json: dict[str, Any],
        noop_seconds: int = DEFAULT_NOOP_SECONDS,
    ) -> dict[str, Any]:
        # Placeholder workflow: keep execution alive for test purposes.
        seconds = max(0, int(noop_seconds))
        workflow.logger.info(
            "Workflow started",
            noop_seconds=seconds,
            has_current_json=True,
            has_last_minute_json=True,
        )
        await workflow.sleep(timedelta(seconds=seconds))
        workflow.logger.info("Workflow completed", noop_seconds=seconds)
        current_keys = sorted(current_json.keys()) if isinstance(current_json, dict) else []
        last_minute_phrases = []
        if isinstance(last_minute_json, dict):
            phrases = last_minute_json.get("phrases")
            if isinstance(phrases, list):
                last_minute_phrases = [p for p in phrases if isinstance(p, str)]
        return {
            "accepted": True,
            "noop_seconds": seconds,
            "current_json_keys": current_keys,
            "last_minute_phrases_count": len(last_minute_phrases),
        }
