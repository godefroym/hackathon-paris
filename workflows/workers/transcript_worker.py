#!/usr/bin/env python3
"""Temporal worker for the TranscriptBatchWorkflow pipeline.

This worker handles the STT-to-fact-check pipeline:

  STT audio → [stt_to_temporal.py] → TranscriptBatchWorkflow
                                         └─→ extract_claims_from_transcript (activity)
                                         └─→ DebateJsonNoopWorkflow (child, per claim)

By default the worker listens on the ``transcript-batch-task-queue``.
Pass ``--combined`` to also run a second worker on ``debate-json-task-queue``
in the same process (convenient for local development without two terminals).
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from temporalio.client import Client
from temporalio.worker import Worker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from debate_config import DEFAULT_TASK_QUEUE, TRANSCRIPT_TASK_QUEUE
from utils.env import load_workflows_env
from workflows.transcript_workflow import TranscriptBatchWorkflow


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Worker Temporal pour TranscriptBatchWorkflow (pipeline STT → fact-check)."
        )
    )
    parser.add_argument(
        "--address",
        default="localhost:7233",
        help="Adresse Temporal frontend (default: localhost:7233)",
    )
    parser.add_argument(
        "--namespace",
        default="default",
        help="Namespace Temporal (default: default)",
    )
    parser.add_argument(
        "--task-queue",
        default=TRANSCRIPT_TASK_QUEUE,
        help=f"Task queue principal (default: {TRANSCRIPT_TASK_QUEUE})",
    )
    parser.add_argument(
        "--combined",
        action="store_true",
        help=(
            "Lancer également un worker sur debate-json-task-queue dans le même processus "
            "(utile en dev pour éviter deux terminaux)."
        ),
    )
    return parser.parse_args()


async def run() -> int:
    args = parse_args()
    env_path = load_workflows_env(override=False)

    try:
        from activities.debate_activities import (
            extract_claims_from_transcript,
            analyze_debate_line,
            check_next_phrase_self_correction,
            post_fact_check_result,
            post_fact_check_to_veristral,
            init_agent_pool,
            shutdown_agent_pool,
        )
    except Exception as exc:
        print(
            "[transcript-worker] impossible de charger les activities. "
            f"Vérifie les dépendances et les clés dans {env_path} "
            "(MISTRAL_API_KEY, FACT_CHECK_POST_URL)."
        )
        print(f"[transcript-worker] détails: {exc}")
        return 1

    client = await Client.connect(args.address, namespace=args.namespace)

    # ── Transcript worker (claim extraction + TranscriptBatchWorkflow) ────────
    transcript_worker = Worker(
        client,
        task_queue=args.task_queue,
        workflows=[TranscriptBatchWorkflow],
        activities=[extract_claims_from_transcript],
    )
    print(
        f"[transcript-worker] listening task_queue={args.task_queue} "
        f"namespace={args.namespace} address={args.address}"
    )

    workers_to_run: list[Worker] = [transcript_worker]

    # ── Optional combined debate worker ────────────────────────────────────────
    if args.combined:
        from workflows.debate_workflow import DebateJsonNoopWorkflow

        debate_worker = Worker(
            client,
            task_queue=DEFAULT_TASK_QUEUE,
            workflows=[DebateJsonNoopWorkflow],
            activities=[
                analyze_debate_line,
                check_next_phrase_self_correction,
                post_fact_check_result,
                post_fact_check_to_veristral,
            ],
        )
        print(
            f"[debate-worker] combined mode — also listening on "
            f"task_queue={DEFAULT_TASK_QUEUE}"
        )
        workers_to_run.append(debate_worker)

    await init_agent_pool()
    try:
        # Run all workers concurrently.
        await asyncio.gather(*[w.run() for w in workers_to_run])
    finally:
        await shutdown_agent_pool()

    return 0


def main() -> int:
    try:
        return asyncio.run(run())
    except KeyboardInterrupt:
        print("\n[transcript-worker] stop requested (Ctrl+C).")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
