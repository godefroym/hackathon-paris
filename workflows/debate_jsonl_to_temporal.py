#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TextIO

from temporalio.client import Client

from debate_workflow import (
    DEFAULT_NOOP_SECONDS,
    DEFAULT_TASK_QUEUE,
    DebateJsonNoopWorkflow,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Lit du JSONL (fichier ou stdin) et cree un workflow Temporal "
            "par ligne JSON."
        )
    )
    parser.add_argument(
        "--input-jsonl",
        default="-",
        help="Chemin JSONL en entree, ou '-' pour stdin (default)",
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
        help=f"Task queue cible (default: {DEFAULT_TASK_QUEUE})",
    )
    parser.add_argument(
        "--workflow-id-prefix",
        default="debate-line",
        help="Prefix des workflow ids (default: debate-line)",
    )
    parser.add_argument(
        "--noop-seconds",
        type=int,
        default=DEFAULT_NOOP_SECONDS,
        help=f"Duree du workflow no-op (default: {DEFAULT_NOOP_SECONDS})",
    )
    parser.add_argument(
        "--stop-on-invalid-json",
        action="store_true",
        help="Stopper au premier JSON invalide (default: ignorer et continuer)",
    )
    return parser.parse_args()


def build_workflow_id(prefix: str, sequence: int) -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    suffix = uuid.uuid4().hex[:10]
    return f"{prefix}-{now}-{sequence:06d}-{suffix}"


def format_utc_iso_millis(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def parse_payload_timestamp(payload: dict[str, Any]) -> datetime:
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        raw = metadata.get("timestamp")
        if isinstance(raw, str):
            normalized = raw.strip()
            if normalized:
                try:
                    parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        return parsed.replace(tzinfo=timezone.utc)
                    return parsed.astimezone(timezone.utc)
                except ValueError:
                    pass
                # Backward compatibility with elapsed timestamps from old payloads.
                for fmt in ("%H:%M:%S.%f", "%H:%M:%S", "%M:%S.%f", "%M:%S"):
                    try:
                        parsed_time = datetime.strptime(normalized, fmt)
                        now = datetime.now(timezone.utc)
                        hour = parsed_time.hour if "%H" in fmt else 0
                        return now.replace(
                            hour=hour,
                            minute=parsed_time.minute,
                            second=parsed_time.second,
                            microsecond=parsed_time.microsecond,
                        )
                    except ValueError:
                        continue
    return datetime.now(timezone.utc)


def extract_phrase(payload: dict[str, Any]) -> str:
    current = payload.get("affirmation_courante")
    if isinstance(current, str) and current.strip():
        return current.strip()
    fallback = payload.get("affirmation")
    if isinstance(fallback, str) and fallback.strip():
        return fallback.strip()
    return ""


def build_last_minute_json(
    *,
    current_payload: dict[str, Any],
    window_payloads: list[tuple[datetime, dict[str, Any]]],
) -> dict[str, Any]:
    phrases: list[str] = []
    for _, payload in window_payloads:
        phrase = extract_phrase(payload)
        if phrase:
            phrases.append(phrase)

    from_timestamp = (
        format_utc_iso_millis(window_payloads[0][0]) if window_payloads else None
    )
    to_timestamp = format_utc_iso_millis(window_payloads[-1][0]) if window_payloads else None

    return {
        "personne": current_payload.get("personne", ""),
        "question_posee": current_payload.get("question_posee", ""),
        "phrases": phrases,
        "metadata": {
            "window_seconds": 60,
            "from_timestamp": from_timestamp,
            "to_timestamp": to_timestamp,
            "phrases_count": len(phrases),
        },
    }


async def run() -> int:
    args = parse_args()
    client = await Client.connect(args.address, namespace=args.namespace)

    if args.input_jsonl == "-":
        input_handle = sys.stdin
        should_close = False
    else:
        path = Path(args.input_jsonl)
        input_handle = path.open("r", encoding="utf-8")
        should_close = True

    total_lines = 0
    invalid_lines = 0
    submitted = 0
    recent_payloads: deque[tuple[datetime, dict[str, Any]]] = deque()
    try:
        for line in input_handle:
            total_lines += 1
            raw = line.strip()
            if not raw:
                continue

            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                invalid_lines += 1
                print(
                    f"[jsonl-to-temporal] ligne {total_lines} invalide: {exc}",
                    file=sys.stderr,
                )
                if args.stop_on_invalid_json:
                    raise
                continue

            if not isinstance(payload, dict):
                payload = {"payload": payload}

            payload_timestamp = parse_payload_timestamp(payload)
            recent_payloads.append((payload_timestamp, payload))
            cutoff = payload_timestamp - timedelta(seconds=60)
            while recent_payloads and recent_payloads[0][0] < cutoff:
                recent_payloads.popleft()

            window_snapshot = list(recent_payloads)
            last_minute_json = build_last_minute_json(
                current_payload=payload,
                window_payloads=window_snapshot,
            )

            submitted += 1
            workflow_id = build_workflow_id(args.workflow_id_prefix, submitted)
            await client.start_workflow(
                DebateJsonNoopWorkflow.run,
                args=[payload, last_minute_json, args.noop_seconds],
                id=workflow_id,
                task_queue=args.task_queue,
            )
            print(
                "[jsonl-to-temporal] submitted "
                f"workflow_id={workflow_id} noop_seconds={args.noop_seconds} "
                f"last_minute_phrases={last_minute_json['metadata']['phrases_count']}",
                file=sys.stderr,
            )
    finally:
        if should_close:
            input_handle.close()

    print(
        "[jsonl-to-temporal] done "
        f"total_lines={total_lines} invalid_lines={invalid_lines} submitted={submitted}",
        file=sys.stderr,
    )
    return 0


def main() -> int:
    try:
        return asyncio.run(run())
    except KeyboardInterrupt:
        print("\n[jsonl-to-temporal] stop requested (Ctrl+C).", file=sys.stderr)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
