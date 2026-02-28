#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from debate_workflow import DEFAULT_TASK_QUEUE, DebateJsonNoopWorkflow


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
    client = await Client.connect(args.address, namespace=args.namespace)
    worker = Worker(
        client,
        task_queue=args.task_queue,
        workflows=[DebateJsonNoopWorkflow],
    )
    print(
        f"[temporal-worker] listening task_queue={args.task_queue} "
        f"namespace={args.namespace} address={args.address}"
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
