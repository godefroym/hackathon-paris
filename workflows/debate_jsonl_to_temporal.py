#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import select
import sys
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TextIO

from temporalio.client import Client

from debate_config import (
    DEFAULT_ANALYSIS_TIMEOUT_SECONDS,
    DEFAULT_TASK_QUEUE,
    DEFAULT_VIDEO_DELAY_SECONDS,
    WORKFLOW_TYPE,
)


def parse_args() -> argparse.Namespace:
    video_delay_default = float(
        os.environ.get("VIDEO_STREAM_DELAY_SECONDS", DEFAULT_VIDEO_DELAY_SECONDS)
    )
    analysis_timeout_default = int(
        os.environ.get(
            "FACT_CHECK_ANALYSIS_TIMEOUT_SECONDS", DEFAULT_ANALYSIS_TIMEOUT_SECONDS
        )
    )

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
        "--video-delay-seconds",
        type=float,
        default=video_delay_default,
        help=(
            "Delai video cible (sec). Le launcher calcule un timestamp cible absolu "
            "par phrase (debut estime + video_delay), puis deduit le delai restant."
        ),
    )
    parser.add_argument(
        "--analysis-timeout-seconds",
        type=int,
        default=analysis_timeout_default,
        help=(
            "Timeout de l'activite d'analyse (sec). "
            f"default: {analysis_timeout_default}"
        ),
    )
    parser.add_argument(
        "--noop-seconds",
        type=float,
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--max-wait-next-phrase-seconds",
        type=float,
        default=1.0,
        help=(
            "En stdin, attente max de la phrase suivante avant envoi de la phrase "
            "en attente sans next_json (default: 1.0)."
        ),
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
    previous_phrases: list[str] = []
    window_len = len(window_payloads)
    for idx, (_, payload) in enumerate(window_payloads):
        phrase = extract_phrase(payload)
        if phrase:
            phrases.append(phrase)
            # Contexte de la derniere minute sans la phrase courante.
            if idx < window_len - 1:
                previous_phrases.append(phrase)

    from_timestamp = (
        format_utc_iso_millis(window_payloads[0][0]) if window_payloads else None
    )
    to_timestamp = format_utc_iso_millis(window_payloads[-1][0]) if window_payloads else None

    return {
        "personne": current_payload.get("personne", ""),
        "question_posee": current_payload.get("question_posee", ""),
        "phrases": phrases,
        "previous_phrases": previous_phrases,
        "metadata": {
            "window_seconds": 60,
            "from_timestamp": from_timestamp,
            "to_timestamp": to_timestamp,
            "phrases_count": len(phrases),
            "previous_phrases_count": len(previous_phrases),
        },
    }


async def run() -> int:
    args = parse_args()
    client = await Client.connect(args.address, namespace=args.namespace)
    video_delay_seconds = max(
        0.0,
        float(args.video_delay_seconds if args.noop_seconds is None else args.noop_seconds),
    )
    analysis_timeout_seconds = max(1, int(args.analysis_timeout_seconds))

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
    pending_item: dict[str, Any] | None = None
    last_payload_timestamp: datetime | None = None

    async def submit_item(
        *,
        item: dict[str, Any],
        next_payload: dict[str, Any] | None,
    ) -> None:
        nonlocal submitted
        now_utc = datetime.now(timezone.utc)
        estimated_start_timestamp = item["estimated_start_timestamp"]
        target_post_timestamp = estimated_start_timestamp + timedelta(
            seconds=video_delay_seconds
        )
        computed_post_delay_seconds = max(
            0.0, (target_post_timestamp - now_utc).total_seconds()
        )
        lateness_seconds = max(
            0.0, (now_utc - target_post_timestamp).total_seconds()
        )
        submitted += 1
        workflow_id = build_workflow_id(args.workflow_id_prefix, submitted)
        await client.start_workflow(
            WORKFLOW_TYPE,
            args=[
                item["payload"],
                item["last_minute_json"],
                computed_post_delay_seconds,
                analysis_timeout_seconds,
                next_payload,
            ],
            id=workflow_id,
            task_queue=args.task_queue,
        )
        next_phrase = extract_phrase(next_payload) if isinstance(next_payload, dict) else ""
        print(
            "[jsonl-to-temporal] submitted "
            f"workflow_id={workflow_id} "
            f"payload_timestamp={format_utc_iso_millis(item['payload_timestamp'])} "
            f"estimated_start_timestamp={format_utc_iso_millis(estimated_start_timestamp)} "
            f"target_post_timestamp={format_utc_iso_millis(target_post_timestamp)} "
            f"submit_timestamp={format_utc_iso_millis(now_utc)} "
            f"computed_post_delay_seconds={computed_post_delay_seconds:.3f} "
            f"lateness_seconds={lateness_seconds:.3f} "
            f"analysis_timeout_seconds={analysis_timeout_seconds} "
            f"last_minute_phrases={item['last_minute_json']['metadata']['phrases_count']} "
            f"has_next_phrase={bool(next_phrase)}",
            file=sys.stderr,
        )

    async def process_raw_line(raw: str, line_number: int) -> None:
        nonlocal invalid_lines, pending_item, last_payload_timestamp
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            invalid_lines += 1
            print(
                f"[jsonl-to-temporal] ligne {line_number} invalide: {exc}",
                file=sys.stderr,
            )
            if args.stop_on_invalid_json:
                raise
            return

        if not isinstance(payload, dict):
            payload = {"payload": payload}

        payload_timestamp = parse_payload_timestamp(payload)
        estimated_start_timestamp = last_payload_timestamp or payload_timestamp
        if pending_item is not None:
            await submit_item(
                item=pending_item,
                next_payload=payload,
            )

        recent_payloads.append((payload_timestamp, payload))
        cutoff = payload_timestamp - timedelta(seconds=60)
        while recent_payloads and recent_payloads[0][0] < cutoff:
            recent_payloads.popleft()

        window_snapshot = list(recent_payloads)
        last_minute_json = build_last_minute_json(
            current_payload=payload,
            window_payloads=window_snapshot,
        )
        pending_item = {
            "payload": payload,
            "payload_timestamp": payload_timestamp,
            "estimated_start_timestamp": estimated_start_timestamp,
            "last_minute_json": last_minute_json,
        }
        last_payload_timestamp = payload_timestamp

    try:
        if args.input_jsonl == "-":
            max_wait = max(0.0, float(args.max_wait_next_phrase_seconds))
            while True:
                timeout = max_wait if pending_item is not None else None
                ready, _, _ = select.select([input_handle], [], [], timeout)
                if not ready:
                    if pending_item is not None:
                        await submit_item(
                            item=pending_item,
                            next_payload=None,
                        )
                        pending_item = None
                    continue

                line = input_handle.readline()
                if line == "":
                    break
                total_lines += 1
                raw = line.strip()
                if not raw:
                    continue
                await process_raw_line(raw, total_lines)
        else:
            for line in input_handle:
                total_lines += 1
                raw = line.strip()
                if not raw:
                    continue
                await process_raw_line(raw, total_lines)

        if pending_item is not None:
            await submit_item(
                item=pending_item,
                next_payload=None,
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
