#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from temporalio.client import Client
from temporalio.worker import Worker

# Support direct execution: `python workers/debate_worker.py`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from debate_config import DEFAULT_TASK_QUEUE
from utils.env import load_workflows_env
from workflows.debate_workflow import DebateJsonNoopWorkflow


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
    env_path = load_workflows_env(override=False)
    try:
        from activities.debate_activities import (
            analyze_debate_line,
            check_next_phrase_self_correction,
            post_fact_check_result,
            post_fact_check_to_veristral,
            init_agent_pool,
            shutdown_agent_pool,
        )
    except Exception as exc:
        print(
            "[temporal-worker] impossible de charger les activities. "
            f"Verifie les dependances et les cles dans {env_path} "
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
            post_fact_check_to_veristral,
        ],
    )
    print(
        f"[temporal-worker] listening task_queue={args.task_queue} "
        f"namespace={args.namespace} address={args.address}"
    )
    await init_agent_pool()
    try:
        await worker.run()
    finally:
        await shutdown_agent_pool()
    return 0


def main() -> int:
    try:
        return asyncio.run(run())
    except KeyboardInterrupt:
        print("\n[temporal-worker] stop requested (Ctrl+C).")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
