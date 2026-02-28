#!/usr/bin/env python3
from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow

from debate_config import (
    DEFAULT_ANALYSIS_TIMEOUT_SECONDS,
    DEFAULT_POST_TIMEOUT_SECONDS,
    DEFAULT_TASK_QUEUE,
    DEFAULT_VIDEO_DELAY_SECONDS,
    WORKFLOW_TYPE,
)

ANALYZE_ACTIVITY_NAME = "analyze_debate_line"
POST_ACTIVITY_NAME = "post_fact_check_result"


@workflow.defn(name=WORKFLOW_TYPE)
class DebateJsonNoopWorkflow:
    @workflow.run
    async def run(
        self,
        current_json: dict[str, Any],
        last_minute_json: dict[str, Any],
        post_delay_seconds: float = DEFAULT_VIDEO_DELAY_SECONDS,
        analysis_timeout_seconds: int = DEFAULT_ANALYSIS_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        # Run analysis first, then wait the remaining stream-delay time before POST.
        delay_before_post = max(0.0, float(post_delay_seconds))
        analysis_timeout = max(1, int(analysis_timeout_seconds))
        workflow.logger.info(
            "Workflow started",
            requested_delay_before_post_seconds=delay_before_post,
            analysis_timeout_seconds=analysis_timeout,
            has_current_json=True,
            has_last_minute_json=True,
        )

        analysis_started = workflow.time()
        analysis_result = await workflow.execute_activity(
            ANALYZE_ACTIVITY_NAME,
            args=[current_json, last_minute_json],
            start_to_close_timeout=timedelta(seconds=analysis_timeout),
        )
        analysis_elapsed = max(0.0, workflow.time() - analysis_started)
        remaining_delay = max(0.0, delay_before_post - analysis_elapsed)
        if remaining_delay > 0:
            await workflow.sleep(remaining_delay)

        post_result = await workflow.execute_activity(
            POST_ACTIVITY_NAME,
            args=[analysis_result],
            start_to_close_timeout=timedelta(seconds=DEFAULT_POST_TIMEOUT_SECONDS),
        )

        workflow.logger.info(
            "Workflow completed",
            analysis_elapsed_seconds=analysis_elapsed,
            remaining_delay_seconds=remaining_delay,
        )
        current_keys = sorted(current_json.keys()) if isinstance(current_json, dict) else []
        last_minute_phrases = []
        if isinstance(last_minute_json, dict):
            phrases = last_minute_json.get("phrases")
            if isinstance(phrases, list):
                last_minute_phrases = [p for p in phrases if isinstance(p, str)]
        return {
            "accepted": True,
            "requested_delay_before_post_seconds": delay_before_post,
            "analysis_timeout_seconds": analysis_timeout,
            "analysis_elapsed_seconds": analysis_elapsed,
            "remaining_delay_seconds": remaining_delay,
            "current_json_keys": current_keys,
            "last_minute_phrases_count": len(last_minute_phrases),
            "analysis_result": analysis_result,
            "post_result": post_result,
        }
