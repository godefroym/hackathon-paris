#!/usr/bin/env python3
"""Temporal workflow: STT transcript window → claim extraction → child fact-checks.

Pipeline
--------
1. extract_claims_from_transcript  – fast Ministral model identifies checkworthy facts
2. For each extracted claim (≤ MAX_CLAIMS_PER_BATCH), spawn a child
   DebateJsonNoopWorkflow that runs the full specialist pipeline.

Design notes
------------
* Only genuinely verifiable claims are fact-checked. The extractor is
  intentionally conservative: 0-2 claims per 20-second window is normal.
* Child workflows are started asynchronously (fire-and-forget) so this
  workflow completes quickly. The child handles its own retry/delay/post logic.
* The transcript window context is forwarded to the child as ``last_minute_json``
  so the specialist agents have the conversational backdrop.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

from debate_config import (
    DEFAULT_ANALYSIS_TIMEOUT_SECONDS,
    DEFAULT_EXTRACTION_TIMEOUT_SECONDS,
    DEFAULT_VIDEO_DELAY_SECONDS,
    MAX_CLAIMS_PER_BATCH,
    TRANSCRIPT_WORKFLOW_TYPE,
    WORKFLOW_TYPE,
)

# ── Activity names ────────────────────────────────────────────────────────────
EXTRACT_CLAIMS_ACTIVITY_NAME = "extract_claims_from_transcript"

# ── Retry policies ────────────────────────────────────────────────────────────
_EXTRACTION_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=10),
    maximum_attempts=3,
)


@workflow.defn(name=TRANSCRIPT_WORKFLOW_TYPE)
class TranscriptBatchWorkflow:
    """Orchestrates claim extraction from a STT window and fans out to child fact-checks.

    Input (all fields are optional with sensible defaults):

    - ``sentences``          – list of STT sentence dicts, each with
                               ``text`` / ``affirmation_courante``, ``personne``,
                               ``question_posee``, and optionally ``timestamp``.
    - ``personne``           – speaker name (fallback when sentences lack it).
    - ``question_posee``     – journalist's question (fallback).
    - ``source_video``       – stream identifier for provenance.
    - ``window_start``       – ISO-8601 UTC timestamp of the window's first sentence.
    - ``window_end``         – ISO-8601 UTC timestamp of the window's last sentence.
    - ``post_delay_seconds`` – video-sync delay forwarded to every child workflow.
    - ``analysis_timeout_seconds`` – fact-check timeout forwarded to every child.
    """

    @workflow.run
    async def run(self, batch: dict[str, Any]) -> dict[str, Any]:
        personne: str = str(batch.get("personne", "")).strip()
        question_posee: str = str(batch.get("question_posee", "")).strip()
        source_video: str = str(batch.get("source_video", "")).strip()
        sentences: list[dict] = batch.get("sentences", [])
        window_start: str = str(batch.get("window_start", "")).strip()
        window_end: str = str(batch.get("window_end", "")).strip()
        post_delay_seconds: float = float(
            batch.get("post_delay_seconds", DEFAULT_VIDEO_DELAY_SECONDS)
        )
        analysis_timeout: int = int(
            batch.get("analysis_timeout_seconds", DEFAULT_ANALYSIS_TIMEOUT_SECONDS)
        )
        extraction_timeout: int = int(
            batch.get("extraction_timeout_seconds", DEFAULT_EXTRACTION_TIMEOUT_SECONDS)
        )

        workflow.logger.info(
            "TranscriptBatchWorkflow started",
            sentences_count=len(sentences),
            personne=personne,
            window_start=window_start,
            window_end=window_end,
        )

        # ── Step 1: claim extraction ──────────────────────────────────────────
        extraction_input = {
            "sentences": sentences,
            "personne": personne,
            "question_posee": question_posee,
        }

        try:
            extraction_result = await workflow.execute_activity(
                EXTRACT_CLAIMS_ACTIVITY_NAME,
                args=[extraction_input],
                start_to_close_timeout=timedelta(seconds=extraction_timeout),
                retry_policy=_EXTRACTION_RETRY,
            )
        except Exception as exc:  # noqa: BLE001
            workflow.logger.error("Claim extraction failed", error=str(exc))
            return {
                "accepted": True,
                "error": str(exc),
                "claims_extracted": 0,
                "children_started": 0,
            }

        claims: list[dict] = []
        if isinstance(extraction_result, dict):
            raw_claims = extraction_result.get("claims", [])
            if isinstance(raw_claims, list):
                claims = [c for c in raw_claims if isinstance(c, dict)]

        # Guard against over-extraction.
        if len(claims) > MAX_CLAIMS_PER_BATCH:
            workflow.logger.warning(
                "Extractor returned more claims than allowed — truncating",
                returned=len(claims),
                max=MAX_CLAIMS_PER_BATCH,
            )
            claims = claims[:MAX_CLAIMS_PER_BATCH]

        workflow.logger.info("Claims extracted", count=len(claims))

        if not claims:
            return {
                "accepted": True,
                "claims_extracted": 0,
                "children_started": 0,
                "window_start": window_start,
                "window_end": window_end,
            }

        # ── Step 2: build shared context (last_minute_json) ───────────────────
        sentence_texts = [
            str(s.get("text", s.get("affirmation_courante", s.get("affirmation", ""))))
            for s in sentences
            if isinstance(s, dict)
        ]
        last_minute_json = _build_last_minute_json(
            sentences=sentences,
            sentence_texts=sentence_texts,
            personne=personne,
            question_posee=question_posee,
            window_start=window_start,
            window_end=window_end,
            source_video=source_video,
        )

        # ── Step 3: spawn child workflows ─────────────────────────────────────
        child_ids: list[str] = []
        for idx, claim in enumerate(claims):
            child_id = await self._start_child_fact_check(
                claim=claim,
                last_minute_json=last_minute_json,
                window_start=window_start,
                idx=idx,
                post_delay_seconds=post_delay_seconds,
                analysis_timeout=analysis_timeout,
            )
            if child_id:
                child_ids.append(child_id)

        workflow.logger.info(
            "TranscriptBatchWorkflow completed",
            claims_extracted=len(claims),
            children_started=len(child_ids),
        )

        return {
            "accepted": True,
            "claims_extracted": len(claims),
            "children_started": len(child_ids),
            "child_workflow_ids": child_ids,
            "window_start": window_start,
            "window_end": window_end,
            "claims": [
                {"affirmation": c.get("affirmation", ""), "type_claim": c.get("type_claim", "")}
                for c in claims
            ],
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _start_child_fact_check(
        self,
        *,
        claim: dict[str, Any],
        last_minute_json: dict[str, Any],
        window_start: str,
        idx: int,
        post_delay_seconds: float,
        analysis_timeout: int,
    ) -> str | None:
        """Start a child DebateJsonNoopWorkflow for a single claim.

        Returns the child workflow ID on success, or None on failure.
        The parent does NOT await the child's result — fire-and-forget.
        """
        affirmation = str(claim.get("affirmation", "")).strip()
        if not affirmation:
            return None

        # Build the current_json in the format expected by DebateJsonNoopWorkflow.
        current_json: dict[str, Any] = {
            "personne": str(claim.get("personne", "")).strip(),
            "question_posee": str(claim.get("question_posee", "")).strip(),
            "affirmation": affirmation,
            "affirmation_courante": affirmation,
            "metadata": {
                "type_claim": str(claim.get("type_claim", "autre")),
                "contexte": str(claim.get("contexte", "")).strip(),
                "timestamp": window_start,
                "source": "stt_batch",
            },
        }
        if window_start:
            current_json["timestamp"] = window_start

        # Build a unique child workflow ID.
        safe_ts = window_start.replace(":", "").replace("-", "").replace(".", "")[:20]
        child_workflow_id = (
            f"fact-check-stt-{safe_ts}-{idx:02d}-"
            f"{affirmation[:20].lower().replace(' ', '_').replace('/', '_')}"
        )
        # Trim to a reasonable length.
        child_workflow_id = child_workflow_id[:120]

        try:
            await workflow.start_child_workflow(
                WORKFLOW_TYPE,
                args=[
                    current_json,
                    last_minute_json,
                    post_delay_seconds,
                    analysis_timeout,
                    # next_json is no longer passed at startup; the ingestion
                    # layer delivers it via the ``next_sentence`` signal once
                    # the following speech batch is collected.
                ],
                id=child_workflow_id,
                task_queue="debate-json-task-queue",
                # Do not wait for the result; the child handles its own lifecycle.
                parent_close_policy=workflow.ParentClosePolicy.ABANDON,
            )
            workflow.logger.info(
                "Child fact-check workflow started",
                child_id=child_workflow_id,
                affirmation_preview=affirmation[:80],
                type_claim=claim.get("type_claim", ""),
            )
            return child_workflow_id
        except Exception as exc:  # noqa: BLE001
            workflow.logger.error(
                "Failed to start child workflow",
                child_id=child_workflow_id,
                error=str(exc),
            )
            return None


# ── Helpers ───────────────────────────────────────────────────────────────────


def _build_last_minute_json(
    *,
    sentences: list[dict],
    sentence_texts: list[str],
    personne: str,
    question_posee: str,
    window_start: str,
    window_end: str,
    source_video: str,
) -> dict[str, Any]:
    """Build the ``last_minute_json`` payload forwarded to child workflows.

    The batch window becomes the conversational context so specialist agents can
    interpret the claim in its proper speech backdrop.
    """
    # previous_phrases = all but the last sentence (mirrors debate_jsonl_to_temporal logic)
    previous_phrases = sentence_texts[:-1] if len(sentence_texts) > 1 else sentence_texts

    return {
        "personne": personne,
        "question_posee": question_posee,
        "phrases": sentence_texts,
        "previous_phrases": previous_phrases,
        "metadata": {
            "window_seconds": DEFAULT_VIDEO_DELAY_SECONDS,
            "from_timestamp": window_start,
            "to_timestamp": window_end,
            "phrases_count": len(sentence_texts),
            "previous_phrases_count": len(previous_phrases),
            "source_video": source_video,
            "origin": "stt_batch",
        },
    }


# ── Manual smoke-test ─────────────────────────────────────────────────────────
# Run directly to submit a fake batch to a local Temporal:
#
#   cd workflows
#   uv run python workflows/transcript_workflow.py
#
# Requires a running Temporal dev server and a running transcript_worker:
#   temporal server start-dev --db-filename temporal.db --ui-port 8233
#   uv run python workers/transcript_worker.py
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import asyncio
    import uuid

    from temporalio.client import Client

    from debate_config import TRANSCRIPT_TASK_QUEUE

    _FAKE_BATCH = {
        "personne": "Jean Dupont",
        "question_posee": "Quel est le bilan économique de votre gouvernement ?",
        "source_video": "BFM TV",
        "window_start": "2026-03-01T20:15:00.000Z",
        "window_end": "2026-03-01T20:15:20.000Z",
        "post_delay_seconds": 5.0,
        "analysis_timeout_seconds": 60,
        "sentences": [
            {
                "text": "Nous avons créé 200 000 emplois l'année dernière.",
                "personne": "Jean Dupont",
                "question_posee": "Quel est le bilan économique de votre gouvernement ?",
                "timestamp": "2026-03-01T20:15:02.000Z",
            },
            {
                "text": "La croissance économique est à 2,5 % cette année.",
                "personne": "Jean Dupont",
                "question_posee": "",
                "timestamp": "2026-03-01T20:15:06.000Z",
            },
            {
                "text": "Le chômage est tombé à 5 % grâce à notre politique de l'emploi.",
                "personne": "Jean Dupont",
                "question_posee": "",
                "timestamp": "2026-03-01T20:15:11.000Z",
            },
            {
                "text": "Nous sommes fiers des résultats obtenus pour les Français.",
                "personne": "Jean Dupont",
                "question_posee": "",
                "timestamp": "2026-03-01T20:15:16.000Z",
            },
        ],
    }

    async def _main() -> None:
        client = await Client.connect("localhost:7233")
        workflow_id = f"smoke-transcript-{uuid.uuid4().hex[:8]}"
        print(f"Starting TranscriptBatchWorkflow  id={workflow_id}")
        print(f"  sentences : {len(_FAKE_BATCH['sentences'])}")
        print(f"  personne  : {_FAKE_BATCH['personne']}")
        print(f"  task queue: {TRANSCRIPT_TASK_QUEUE}\n")

        handle = await client.start_workflow(
            TRANSCRIPT_WORKFLOW_TYPE,
            args=[_FAKE_BATCH],
            id=workflow_id,
            task_queue=TRANSCRIPT_TASK_QUEUE,
        )
        print("Workflow submitted — waiting for result …")
        result = await handle.result()
        import json
        print("\nResult:")
        print(json.dumps(result, indent=2, ensure_ascii=False))

    asyncio.run(_main())
