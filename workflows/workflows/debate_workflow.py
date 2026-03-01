#!/usr/bin/env python3
"""Temporal workflow for live debate fact-checking.

Pipeline
--------
1. analyze_debate_line                – full Mistral AI fact-check pipeline
2. wait for ``next_sentence`` signal  – block until the ingestion layer delivers
     the speaker's subsequent speech (or until the signal deadline expires).
3. check_next_phrase_self_correction  – detect speaker self-correction using
     the signalled content; may suppress the post or adjust its tone.
4. (sleep) wait remaining video delay – sync verdict timing with live broadcast
     so the overlay appears at the right moment on OBS.
5. post_fact_check_result             – HTTP POST verdict to stream service

Signal: ``next_sentence``
    Payload: ``{"affirmation": str, "personne": str}``
    Sent by the ingestion layer (stt_to_temporal.py) once the next speech
    batch has been collected.  If no signal arrives before the deadline the
    workflow proceeds with no next-phrase context (no correction assumed).

Each activity has its own retry policy.  The self-correction step is
fault-tolerant: a transient failure defaults to "no correction detected" so
that a flaky network call never silently suppresses a valid verdict.
"""
from __future__ import annotations

import sys
from pathlib import Path

# When this file is executed directly (python debate_workflow.py) the parent
# workflows/ directory is not on sys.path.  Add it so that debate_config and
# the activities package resolve correctly in both run modes.
# Note: .resolve() is intentionally omitted — Temporal's workflow sandbox
# restricts pathlib.Path.resolve, and __file__ is already absolute.
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

from debate_config import (
    DEFAULT_ANALYSIS_TIMEOUT_SECONDS,
    DEFAULT_POST_TIMEOUT_SECONDS,
    DEFAULT_SIGNAL_WAIT_MIN_SECONDS,
    DEFAULT_VIDEO_DELAY_SECONDS,
    NEXT_SENTENCE_SIGNAL,
    WORKFLOW_TYPE,
)

# ── Activity names (must match names registered in the worker) ────────────────
ANALYZE_ACTIVITY_NAME = "analyze_debate_line"
SELF_CORRECTION_ACTIVITY_NAME = "check_next_phrase_self_correction"
POST_ACTIVITY_NAME = "post_fact_check_result"
POST_VERISTRAL_ACTIVITY_NAME = "post_fact_check_to_veristral"

# ── Retry policies ────────────────────────────────────────────────────────────
# Analysis is expensive; give it a few attempts with generous backoff.
_ANALYSIS_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=20),
    maximum_attempts=3,
)

# Self-correction is quick and low-stakes; fail fast.
_SELF_CORRECTION_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=10),
    maximum_attempts=2,
)

# Posting may hit a temporarily unavailable HTTP service; retry more aggressively.
_POST_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=5,
)

# Same policy re-used for the Veristral secondary endpoint.
_POST_VERISTRAL_RETRY = _POST_RETRY


@workflow.defn(name=WORKFLOW_TYPE)
class DebateJsonNoopWorkflow:
    """Orchestrates the real-time fact-check pipeline for a single debate sentence."""

    def __init__(self) -> None:
        # Populated by the ``next_sentence`` signal sent from the ingestion layer.
        self._next_sentence_payload: dict[str, Any] | None = None

    # ── Signal handler ────────────────────────────────────────────────────────

    @workflow.signal(name=NEXT_SENTENCE_SIGNAL)
    def receive_next_sentence(self, payload: dict[str, Any]) -> None:
        """Receive the speaker's subsequent content from the ingestion layer.

        This signal is expected to arrive during the video-sync sleep so the
        reviewer has real post-fact speech to analyse.  Multiple signals are
        merged (later arrivals extend the affirmation text).
        """
        if not isinstance(payload, dict):
            return
        if self._next_sentence_payload is None:
            self._next_sentence_payload = payload
        else:
            # Append additional sentences to the existing payload.
            existing = str(self._next_sentence_payload.get("affirmation", "")).strip()
            incoming = str(payload.get("affirmation", "")).strip()
            if incoming and incoming not in existing:
                self._next_sentence_payload = {
                    **self._next_sentence_payload,
                    "affirmation": f"{existing} {incoming}".strip(),
                }
        workflow.logger.info(
            "next_sentence signal received",
            affirmation_preview=str(payload.get("affirmation", ""))[:80],
        )

    # ── Public entry-point ────────────────────────────────────────────────────

    @workflow.run
    async def run(
        self,
        current_json: dict[str, Any],
        last_minute_json: dict[str, Any],
        post_delay_seconds: float = DEFAULT_VIDEO_DELAY_SECONDS,
        analysis_timeout_seconds: int = DEFAULT_ANALYSIS_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        delay_before_post = max(0.0, float(post_delay_seconds))
        analysis_timeout = max(1, int(analysis_timeout_seconds))

        workflow.logger.info(
            "Workflow started",
            delay_before_post_seconds=delay_before_post,
            analysis_timeout_seconds=analysis_timeout,
        )

        analysis_started = workflow.time()

        # ── Step 1: fact-check analysis ───────────────────────────────────────
        analysis_result = await self._run_analysis(
            current_json, last_minute_json, analysis_timeout
        )

        # ── Step 2: wait for ``next_sentence`` signal ─────────────────────────
        # Block until the ingestion layer sends the speaker's subsequent speech,
        # or until the signal deadline expires.  The deadline is whatever time
        # remains of the video-delay budget, with a guaranteed minimum so the
        # workflow doesn't give up immediately when analysis was slow.
        elapsed_after_analysis = max(0.0, workflow.time() - analysis_started)
        signal_timeout = max(
            float(DEFAULT_SIGNAL_WAIT_MIN_SECONDS),
            delay_before_post - elapsed_after_analysis,
        )
        signal_received = await self._wait_for_signal(signal_timeout)
        workflow.logger.info(
            "Signal wait complete",
            signal_received=signal_received,
            signal_timeout_seconds=signal_timeout,
        )

        # ── Step 3: self-correction detection (with signalled next content) ───
        correction_check = await self._run_self_correction_check(
            current_json, self._next_sentence_payload, last_minute_json, analysis_timeout
        )

        # ── Step 4: wait remaining video delay before showing OBS overlay ─────
        # Any time already spent (analysis + signal wait) is subtracted so the
        # overlay appears at exactly post_delay_seconds after workflow start.
        elapsed_after_check = max(0.0, workflow.time() - analysis_started)
        await self._wait_remaining_delay(delay_before_post, elapsed_after_check)

        # ── Step 5: decide whether to post ───────────────────────────────────
        skip, skip_reason = self._should_skip_post(correction_check)

        # ── Step 6: post to obs-controller or suppress ────────────────────────────
        if skip:
            analysis_result = self._annotate_skipped(analysis_result, skip_reason)
            post_result: dict[str, Any] = {
                "posted": False,
                "skipped": True,
                "reason": "next_phrase_self_correction",
            }
        else:
            post_result = await self._post_result(analysis_result)

        # ── Step 7: post to obs-veristral (always — even when skipped) ────────────
        veristral_result = await self._post_veristral(analysis_result)

        total_elapsed = max(0.0, workflow.time() - analysis_started)

        workflow.logger.info(
            "Workflow completed",
            total_elapsed_seconds=total_elapsed,
            skip_post_due_to_correction=skip,
            had_next_sentence_signal=signal_received,
        )

        return self._build_output(
            current_json=current_json,
            last_minute_json=last_minute_json,
            delay_before_post=delay_before_post,
            analysis_timeout=analysis_timeout,
            elapsed=total_elapsed,
            remaining_delay=max(0.0, delay_before_post - elapsed_after_check),
            correction_check=correction_check,
            skip=skip,
            signal_received=signal_received,
            analysis_result=analysis_result,
            post_result=post_result,
            veristral_result=veristral_result,
        )

    # ── Private activity wrappers ─────────────────────────────────────────────

    async def _wait_for_signal(self, timeout_seconds: float) -> bool:
        """Block until ``next_sentence`` is received or *timeout_seconds* elapses.

        Returns ``True`` if the signal arrived, ``False`` if timed out.
        The signal handler populates ``self._next_sentence_payload``; this
        method simply waits on that condition.
        """
        try:
            await workflow.wait_condition(
                lambda: self._next_sentence_payload is not None,
                timeout=timedelta(seconds=timeout_seconds),
            )
            return True
        except Exception:  # noqa: BLE001 — TimeoutError or any sandbox exception
            return self._next_sentence_payload is not None

    async def _run_analysis(
        self,
        current_json: dict[str, Any],
        last_minute_json: dict[str, Any],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        """Run the full fact-check analysis activity with retries."""
        result = await workflow.execute_activity(
            ANALYZE_ACTIVITY_NAME,
            args=[current_json, last_minute_json],
            start_to_close_timeout=timedelta(seconds=timeout_seconds),
            retry_policy=_ANALYSIS_RETRY,
        )
        return result if isinstance(result, dict) else {"raw": result}

    async def _run_self_correction_check(
        self,
        current_json: dict[str, Any],
        next_json: dict[str, Any] | None,
        last_minute_json: dict[str, Any],
        analysis_timeout: int,
    ) -> dict[str, Any]:
        """Run the self-correction check activity.

        On failure, defaults to ``{"has_next_phrase": False}`` so that a
        transient error never silently suppresses a valid verdict.
        """
        correction_timeout = min(analysis_timeout, 10)
        try:
            result = await workflow.execute_activity(
                SELF_CORRECTION_ACTIVITY_NAME,
                args=[current_json, next_json, last_minute_json],
                start_to_close_timeout=timedelta(seconds=correction_timeout),
                retry_policy=_SELF_CORRECTION_RETRY,
            )
            return result if isinstance(result, dict) else {"has_next_phrase": False}
        except Exception as exc:  # noqa: BLE001
            workflow.logger.warning(
                "Self-correction check failed — defaulting to no-correction",
                error=str(exc),
            )
            return {"has_next_phrase": False, "error": str(exc)}

    async def _post_result(self, analysis_result: dict[str, Any]) -> dict[str, Any]:
        """Post the verdict to obs-controller (primary endpoint) with retries."""
        result = await workflow.execute_activity(
            POST_ACTIVITY_NAME,
            args=[analysis_result],
            start_to_close_timeout=timedelta(seconds=DEFAULT_POST_TIMEOUT_SECONDS),
            retry_policy=_POST_RETRY,
        )
        return result if isinstance(result, dict) else {"posted": True, "raw": result}

    async def _post_veristral(self, analysis_result: dict[str, Any]) -> dict[str, Any]:
        """Post the verdict to obs-veristral (secondary endpoint) with retries."""
        result = await workflow.execute_activity(
            POST_VERISTRAL_ACTIVITY_NAME,
            args=[analysis_result],
            start_to_close_timeout=timedelta(seconds=DEFAULT_POST_TIMEOUT_SECONDS),
            retry_policy=_POST_VERISTRAL_RETRY,
        )
        return result if isinstance(result, dict) else {"posted": True, "raw": result}

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    async def _wait_remaining_delay(delay_before_post: float, elapsed: float) -> None:
        """Sleep for whatever time remains of the video-sync delay."""
        remaining = max(0.0, delay_before_post - elapsed)
        if remaining > 0:
            workflow.logger.info(
                "Waiting for video-sync delay", remaining_seconds=remaining
            )
            await workflow.sleep(remaining)

    @staticmethod
    def _should_skip_post(correction_check: dict[str, Any]) -> tuple[bool, str]:
        """Return ``(skip, reason)`` based on the correction-check result."""
        skip = bool(
            correction_check.get("has_next_phrase")
            and correction_check.get("next_is_correction")
        )
        reason = str(correction_check.get("reason", "")).strip() if skip else ""
        return skip, reason

    @staticmethod
    def _annotate_skipped(
        analysis_result: dict[str, Any], reason: str
    ) -> dict[str, Any]:
        """Attach a ``raison`` field explaining why posting was suppressed."""
        raison = (
            f"Fact-check ignore: {reason}"
            if reason
            else "Fact-check ignore: phrase suivante identifiee comme correction."
        )
        return {**analysis_result, "raison": raison}

    @staticmethod
    def _build_output(
        *,
        current_json: dict[str, Any],
        last_minute_json: dict[str, Any],
        delay_before_post: float,
        analysis_timeout: int,
        elapsed: float,
        remaining_delay: float,
        correction_check: dict[str, Any],
        skip: bool,
        signal_received: bool,
        analysis_result: dict[str, Any],
        post_result: dict[str, Any],
        veristral_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Assemble the final workflow result dict."""
        current_keys = sorted(current_json.keys()) if isinstance(current_json, dict) else []
        previous_phrases = (
            last_minute_json.get("previous_phrases", last_minute_json.get("phrases", []))
            if isinstance(last_minute_json, dict)
            else []
        )
        previous_phrases_count = sum(1 for p in previous_phrases if isinstance(p, str))
        return {
            "accepted": True,
            "requested_delay_before_post_seconds": delay_before_post,
            "analysis_timeout_seconds": analysis_timeout,
            "pre_post_elapsed_seconds": elapsed,
            "remaining_delay_seconds": remaining_delay,
            "current_json_keys": current_keys,
            "last_minute_phrases_count": previous_phrases_count,
            "had_next_sentence_signal": signal_received,
            "correction_check": correction_check,
            "skip_post_due_to_correction": skip,
            "analysis_result": analysis_result,
            "post_result": post_result,
            "veristral_result": veristral_result,
        }


# ── Manual smoke-test ─────────────────────────────────────────────────────────
# Run directly (no worker needed) to verify the workflow can be submitted to a
# local Temporal server:
#
#   cd workflows
#   uv run python workflows/debate_workflow.py
#
# Requires a running Temporal dev server:
#   temporal server start-dev --db-filename temporal.db --ui-port 8233
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import asyncio
    import json
    import uuid

    from temporalio.client import Client

    from debate_config import DEFAULT_TASK_QUEUE

    _FAKE_CURRENT = {
        "personne": "Jean Dupont",
        "question_posee": "Quel est le taux de chômage actuel ?",
        "affirmation": "Le chômage est tombé à 5 % grâce à notre politique.",
        "timestamp": "2026-03-01T20:15:30Z",
    }

    _FAKE_LAST_MINUTE = {
        "phrases": [
            "Nous avons créé 200 000 emplois l'année dernière.",
            "La croissance est de 2,5 %.",
            "Le chômage est tombé à 5 % grâce à notre politique.",
        ],
        "previous_phrases": [
            "Nous avons créé 200 000 emplois l'année dernière.",
            "La croissance est de 2,5 %.",
        ],
        "metadata": {},
    }

    _FAKE_NEXT_SIGNAL_PAYLOAD = {
        "affirmation": "Enfin, je voulais dire 5,2 %.",
        "personne": "Jean Dupont",
    }

    async def _main() -> None:
        client = await Client.connect("localhost:7233")
        workflow_id = f"smoke-test-{uuid.uuid4().hex[:8]}"
        print(f"Starting workflow  id={workflow_id}")
        print(f"  current   : {_FAKE_CURRENT['affirmation']}")
        print(f"  next (sig): {_FAKE_NEXT_SIGNAL_PAYLOAD['affirmation']}")
        print(f"  task queue: {DEFAULT_TASK_QUEUE}\n")

        handle = await client.start_workflow(
            WORKFLOW_TYPE,
            args=[
                _FAKE_CURRENT,
                _FAKE_LAST_MINUTE,
                # post_delay_seconds  — short for smoke-test
                5.0,
                # analysis_timeout_seconds
                30,
            ],
            id=workflow_id,
            task_queue=DEFAULT_TASK_QUEUE,
        )

        # Simulate the ingestion layer sending the next-sentence signal a few
        # seconds after the workflow starts (while the analysis is running).
        await asyncio.sleep(2)
        print(f"Sending '{NEXT_SENTENCE_SIGNAL}' signal …")
        await handle.signal(NEXT_SENTENCE_SIGNAL, _FAKE_NEXT_SIGNAL_PAYLOAD)

        print("Workflow submitted — waiting for result …")
        result = await handle.result()
        print("\nResult:")
        print(json.dumps(result, indent=2, ensure_ascii=False))

    asyncio.run(_main())
