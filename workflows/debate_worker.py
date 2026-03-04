#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import importlib
import os

from temporalio.client import Client
from temporalio.worker import Worker

from debate_config import DEFAULT_TASK_QUEUE
from debate_workflow import DebateJsonNoopWorkflow


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Worker Temporal local pour recevoir les jobs JSON de debat."
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
        default=DEFAULT_TASK_QUEUE,
        help=f"Task queue worker (default: {DEFAULT_TASK_QUEUE})",
    )
    return parser.parse_args()


async def run() -> int:
    args = parse_args()
    impl = os.getenv("FACT_CHECK_ACTIVITY_IMPL", "local").strip().lower()
    module_name = "activities_emma" if impl in {"emma", "activities_emma"} else "activities"
    try:
        activities_module = importlib.import_module(module_name)
        analyze_debate_line = activities_module.analyze_debate_line
        check_next_phrase_self_correction = (
            activities_module.check_next_phrase_self_correction
        )
        post_fact_check_result = activities_module.post_fact_check_result
    except Exception as exc:
        print(
            f"[temporal-worker] impossible de charger {module_name}.py. "
            "Verifie les dependances et les cles dans cle.env "
            "(MISTRAL_API_KEY, FACT_CHECK_POST_URL)."
        )
        print(f"[temporal-worker] details: {exc}")
        return 1

    client = await Client.connect(args.address, namespace=args.namespace)
    worker = Worker(
        client,
        task_queue=args.task_queue,
        workflows=[DebateJsonNoopWorkflow],
        activities=[
            analyze_debate_line,
            check_next_phrase_self_correction,
            post_fact_check_result,
        ],
    )
    print(
        f"[temporal-worker] listening task_queue={args.task_queue} "
        f"namespace={args.namespace} address={args.address} "
        f"activities_module={module_name}"
    )
    await worker.run()
    return 0


def main() -> int:
    try:
        return asyncio.run(run())
    except KeyboardInterrupt:
        print("\n[temporal-worker] stop requested (Ctrl+C).")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
