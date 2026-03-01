"""Per-sentence Temporal ingestion helpers.

Extracted from workers/debate_jsonl_to_temporal.py so that both the standalone
worker script and pipeline.py (``--submission-mode per-sentence``) can share the
same submission logic without code duplication.

The core public API is ``run_per_sentence_bridge()``, which reads sentence dicts
from any ``AsyncIterator[dict]`` source, maintains a 60-second rolling context
window, and submits one ``DebateJsonNoopWorkflow`` per sentence.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator

from temporalio.client import Client

# Lazy-import to avoid circular imports when this module is imported early.
from debate_config import (
    DEFAULT_ANALYSIS_TIMEOUT_SECONDS,
    DEFAULT_TASK_QUEUE,
    DEFAULT_VIDEO_DELAY_SECONDS,
    WORKFLOW_TYPE,
)
from utils.text import extract_affirmation


# ── Timestamp helpers ─────────────────────────────────────────────────────────


def format_utc_iso_millis(dt: datetime) -> str:
    return (
        dt.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def parse_payload_timestamp(payload: dict[str, Any]) -> datetime:
    """Extract a UTC datetime from a sentence payload's metadata.timestamp field."""
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
                # Backward compatibility with elapsed timestamps (MM:SS format).
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


def build_workflow_id(prefix: str, sequence: int) -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    suffix = uuid.uuid4().hex[:10]
    return f"{prefix}-{now}-{sequence:06d}-{suffix}"


# ── Rolling context window ────────────────────────────────────────────────────


def build_last_minute_json(
    *,
    current_payload: dict[str, Any],
    window_payloads: list[tuple[datetime, dict[str, Any]]],
) -> dict[str, Any]:
    """Build a last-60-seconds context object from the rolling window."""
    phrases: list[str] = []
    previous_phrases: list[str] = []
    window_len = len(window_payloads)
    for idx, (_, payload) in enumerate(window_payloads):
        phrase = extract_affirmation(payload)
        if phrase:
            phrases.append(phrase)
            if idx < window_len - 1:
                previous_phrases.append(phrase)

    from_timestamp = (
        format_utc_iso_millis(window_payloads[0][0]) if window_payloads else None
    )
    to_timestamp = (
        format_utc_iso_millis(window_payloads[-1][0]) if window_payloads else None
    )

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


# ── Per-sentence bridge loop ──────────────────────────────────────────────────


async def run_per_sentence_bridge(
    *,
    sentence_source: AsyncIterator[dict],
    client: "Client | None",
    args: argparse.Namespace,
) -> int:
    """Submit one ``DebateJsonNoopWorkflow`` per sentence dict from *sentence_source*.

    *args* must expose:
      - args.task_queue (str)
      - args.workflow_id_prefix (str)
      - args.video_delay_seconds (float)
      - args.analysis_timeout_seconds (int)
      - args.dry_run (bool)

    Returns 0 on success.
    """
    video_delay_seconds = max(0.0, float(args.video_delay_seconds))
    analysis_timeout_seconds = max(1, int(args.analysis_timeout_seconds))

    total_lines = 0
    submitted = 0
    recent_payloads: deque[tuple[datetime, dict[str, Any]]] = deque()
    pending_item: dict[str, Any] | None = None

    async def _submit(
        *,
        item: dict[str, Any],
        next_payload: "dict[str, Any] | None",
        gap_seconds: float,
    ) -> None:
        nonlocal submitted
        computed_post_delay = max(0.0, video_delay_seconds - max(0.0, gap_seconds))
        submitted += 1
        wf_id = build_workflow_id(args.workflow_id_prefix, submitted)

        if args.dry_run:
            phrase = extract_affirmation(item["payload"])
            print(
                f"[per-sentence dry-run] #{submitted:06d} "
                f"gap={gap_seconds:.3f}s delay={computed_post_delay:.3f}s "
                f"phrase={phrase[:80]!r}"
            )
            return

        if client is None:
            return

        await client.start_workflow(
            WORKFLOW_TYPE,
            args=[
                item["payload"],
                item["last_minute_json"],
                computed_post_delay,
                analysis_timeout_seconds,
                next_payload,
            ],
            id=wf_id,
            task_queue=args.task_queue,
        )
        next_phrase = extract_affirmation(next_payload) if isinstance(next_payload, dict) else ""
        print(
            f"[per-sentence] submitted #{submitted:06d} "
            f"id={wf_id} "
            f"gap={gap_seconds:.3f}s "
            f"delay={computed_post_delay:.3f}s "
            f"has_next={bool(next_phrase)}",
            file=sys.stderr,
        )

    async for payload in sentence_source:
        total_lines += 1
        payload_timestamp = parse_payload_timestamp(payload)

        if pending_item is not None:
            gap_seconds = max(
                0.0,
                (payload_timestamp - pending_item["payload_timestamp"]).total_seconds(),
            )
            await _submit(
                item=pending_item,
                next_payload=payload,
                gap_seconds=gap_seconds,
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
            "last_minute_json": last_minute_json,
        }

    # Flush the final pending sentence (no next_payload available).
    if pending_item is not None:
        await _submit(item=pending_item, next_payload=None, gap_seconds=0.0)

    print(
        f"[per-sentence] done total={total_lines} submitted={submitted}",
        file=sys.stderr,
    )
    return 0
