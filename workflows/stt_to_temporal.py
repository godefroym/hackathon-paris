#!/usr/bin/env python3
"""STT-to-Temporal bridge.

Accumulates sentence dicts into time-based windows (~20 s or N sentences) and
submits each window to a TranscriptBatchWorkflow on Temporal.

Sentence dicts arrive via an ``AsyncIterator[dict]``:
- ``sentences_from_queue(q)``  — in-process queue fed by realtime_transcript
                                  (used by pipeline.py — no OS pipe needed)
- ``sentences_from_textio(h)`` — reads a TextIO handle line-by-line via
                                  run_in_executor (file-replay or stdin mode)

Standalone usage (file replay):
    python stt_to_temporal.py --input-jsonl /path/to/stt.jsonl

Standalone usage (dry-run):
    python stt_to_temporal.py --dry-run --input-jsonl /path/to/stt.jsonl

Preferred live usage — via pipeline.py (no pipe, single process):
    python pipeline.py --personne "Jean Dupont" --source-video "TF1 20h"
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, TextIO

# Allow running as a script from repo root.
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
_WORKFLOWS_DIR = _PROJECT_ROOT / "workflows"
if str(_WORKFLOWS_DIR) not in sys.path:
    sys.path.insert(0, str(_WORKFLOWS_DIR))

from temporalio.client import Client

from debate_config import (
    DEFAULT_ANALYSIS_TIMEOUT_SECONDS,
    DEFAULT_STT_BUFFER_SECONDS,
    DEFAULT_STT_MIN_SENTENCES,
    DEFAULT_VIDEO_DELAY_SECONDS,
    NEXT_SENTENCE_SIGNAL,
    TRANSCRIPT_TASK_QUEUE,
    TRANSCRIPT_WORKFLOW_TYPE,
)
from utils.env import load_workflows_env


# ── CLI ────────────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Lit le flux JSONL de realtime_transcript.py, accumule ~20 s de phrases, "
            "puis soumet chaque fenêtre à un TranscriptBatchWorkflow Temporal."
        )
    )
    parser.add_argument(
        "--input-jsonl",
        default="-",
        help="Fichier JSONL STT, ou '-' pour stdin (default: stdin).",
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
        help=f"Task queue Temporal (default: {TRANSCRIPT_TASK_QUEUE})",
    )
    parser.add_argument(
        "--buffer-seconds",
        type=float,
        default=float(os.environ.get("STT_BUFFER_SECONDS", DEFAULT_STT_BUFFER_SECONDS)),
        help=f"Durée de la fenêtre d'accumulation en secondes (default: {DEFAULT_STT_BUFFER_SECONDS})",
    )
    parser.add_argument(
        "--min-sentences",
        type=int,
        default=int(os.environ.get("STT_MIN_SENTENCES", DEFAULT_STT_MIN_SENTENCES)),
        help=(
            f"Flush anticipé quand ce nombre de phrases est atteint "
            f"(default: {DEFAULT_STT_MIN_SENTENCES})"
        ),
    )
    parser.add_argument(
        "--video-delay-seconds",
        type=float,
        default=float(
            os.environ.get("VIDEO_STREAM_DELAY_SECONDS", DEFAULT_VIDEO_DELAY_SECONDS)
        ),
        help="Délai vidéo transmis au workflow enfant (default: 30 s)",
    )
    parser.add_argument(
        "--analysis-timeout-seconds",
        type=int,
        default=int(
            os.environ.get(
                "FACT_CHECK_ANALYSIS_TIMEOUT_SECONDS", DEFAULT_ANALYSIS_TIMEOUT_SECONDS
            )
        ),
        help="Timeout d'analyse transmis au workflow enfant",
    )
    parser.add_argument(
        "--source-video",
        default=os.environ.get("SOURCE_VIDEO", ""),
        help="Identifiant du flux vidéo (champ provenance)",
    )
    parser.add_argument(
        "--workflow-id-prefix",
        default="transcript-batch",
        help="Préfixe des workflow IDs Temporal (default: transcript-batch)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche les batches sans les soumettre à Temporal.",
    )
    return parser.parse_args()


# ── Helpers ────────────────────────────────────────────────────────────────────


def format_utc_iso_millis(dt: datetime) -> str:
    return (
        dt.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def parse_sentence_timestamp(payload: dict[str, Any]) -> datetime:
    """Extract the UTC timestamp from a realtime_transcript.py JSON line."""
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        raw = metadata.get("timestamp")
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
                return (
                    parsed.replace(tzinfo=timezone.utc)
                    if parsed.tzinfo is None
                    else parsed.astimezone(timezone.utc)
                )
            except ValueError:
                pass
    # Fallback: use the top-level timestamp field (older emitters use this).
    raw_top = payload.get("timestamp", "")
    if isinstance(raw_top, str) and raw_top.strip():
        try:
            parsed = datetime.fromisoformat(raw_top.strip().replace("Z", "+00:00"))
            return (
                parsed.replace(tzinfo=timezone.utc)
                if parsed.tzinfo is None
                else parsed.astimezone(timezone.utc)
            )
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def normalize_sentence(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalise a realtime_transcript.py JSON line → TranscriptSentence-shaped dict.

    realtime_transcript.py format:
      { personne, question_posee, affirmation, affirmation_courante,
        metadata: { source_video, timestamp_elapsed, timestamp } }
    """
    text = str(
        payload.get("affirmation_courante")
        or payload.get("affirmation")
        or ""
    ).strip()
    metadata = payload.get("metadata") or {}
    return {
        "text": text,
        "personne": str(payload.get("personne", "")).strip(),
        "question_posee": str(payload.get("question_posee", "")).strip(),
        "timestamp": str(metadata.get("timestamp") or payload.get("timestamp", "")).strip(),
    }


def build_workflow_id(prefix: str, sequence: int) -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    suffix = uuid.uuid4().hex[:8]
    return f"{prefix}-{now}-{sequence:04d}-{suffix}"


# ── Sentence source adapters ─────────────────────────────────────────────────


async def sentences_from_queue(
    q: "asyncio.Queue[dict | None]",
) -> AsyncIterator[dict]:
    """Yield sentence dicts from an in-process asyncio.Queue.

    Stops when the producer pushes the ``None`` sentinel.
    Used by pipeline.py so no OS pipe or JSON serialization round-trip is needed.
    """
    while True:
        item = await q.get()
        if item is None:
            break
        yield item


async def sentences_from_textio(
    handle: TextIO,
) -> AsyncIterator[dict]:
    """Yield parsed sentence dicts from a text stream (file or stdin).

    readline() is wrapped in run_in_executor to avoid blocking the event loop.
    Invalid JSON lines are logged and skipped.
    """
    loop = asyncio.get_running_loop()

    def _read_line() -> "str | None":
        try:
            line = handle.readline()
            return line if line else None  # empty string = EOF
        except (EOFError, KeyboardInterrupt):
            return None

    while True:
        line = await loop.run_in_executor(None, _read_line)
        if line is None:
            break
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            print(
                f"[stt→temporal] JSON invalide, ligne ignorée: {exc}",
                file=sys.stderr,
            )
            continue
        if isinstance(payload, dict):
            yield payload


# ── Batch submission ───────────────────────────────────────────────────────────


# ── Signal helpers ────────────────────────────────────────────────────────────


def _build_next_sentence_signal(sentences: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the payload for a ``next_sentence`` signal from a list of sentences.

    Concatenates the text of all sentences so the reviewer agent receives the
    full subsequent speech as a single affirmation string.
    """
    texts = [str(s.get("text", "")).strip() for s in sentences if isinstance(s, dict)]
    combined = " ".join(t for t in texts if t)
    personne = next(
        (s["personne"] for s in reversed(sentences) if isinstance(s, dict) and s.get("personne")),
        "",
    )
    return {"affirmation": combined, "personne": personne}


async def _send_signals_when_result_ready(
    result_task: asyncio.Task,
    signal_payload: dict[str, Any],
    client: Client,
) -> None:
    """Background task: await the TranscriptBatchWorkflow result, then signal
    each child DebateJsonNoopWorkflow with the next-sentence payload.

    Runs fully asynchronously so it never blocks the sentence-reading loop.
    """
    try:
        result = await result_task
    except Exception as exc:
        print(
            f"[stt→temporal] previous batch failed, skipping signals: {exc}",
            file=sys.stderr,
        )
        return

    if not isinstance(result, dict):
        return

    child_ids: list[str] = result.get("child_workflow_ids", [])
    if not child_ids:
        return

    for child_id in child_ids:
        try:
            handle = client.get_workflow_handle(child_id)
            await handle.signal(NEXT_SENTENCE_SIGNAL, signal_payload)
            print(
                f"[stt→temporal] next_sentence signal → {child_id[:70]}",
                flush=True,
            )
        except Exception as exc:
            print(
                f"[stt→temporal] signal to {child_id[:70]} failed: {exc}",
                file=sys.stderr,
            )


async def submit_batch(
    *,
    client: Client | None,
    batch_sentences: list[dict[str, Any]],
    window_start: datetime,
    window_end: datetime,
    source_video: str,
    post_delay_seconds: float,
    analysis_timeout_seconds: int,
    task_queue: str,
    workflow_id_prefix: str,
    sequence: int,
    dry_run: bool,
) -> "asyncio.Task[Any] | None":
    """Build and optionally submit a TranscriptBatchWorkflow for *batch_sentences*.

    Returns an asyncio Task that will resolve to the workflow result dict
    (containing ``child_workflow_ids``), or *None* for dry-runs / missing client.
    The caller may use this task to dispatch ``next_sentence`` signals to the
    spawned children once the next speech batch is collected.
    """
    if not batch_sentences:
        return

    # Prefer the most recent sentence's speaker/question (most up-to-date context).
    personne = next(
        (s["personne"] for s in reversed(batch_sentences) if s.get("personne")),
        "",
    )
    question_posee = next(
        (s["question_posee"] for s in reversed(batch_sentences) if s.get("question_posee")),
        "",
    )

    batch_payload: dict[str, Any] = {
        "sentences": batch_sentences,
        "personne": personne,
        "question_posee": question_posee,
        "source_video": source_video,
        "window_start": format_utc_iso_millis(window_start),
        "window_end": format_utc_iso_millis(window_end),
        "post_delay_seconds": post_delay_seconds,
        "analysis_timeout_seconds": analysis_timeout_seconds,
    }

    wf_id = build_workflow_id(workflow_id_prefix, sequence)

    if dry_run:
        print(
            f"[dry-run] batch #{sequence:04d}  "
            f"sentences={len(batch_sentences)}  "
            f"speaker={personne!r}  "
            f"window={format_utc_iso_millis(window_start)}"
            f"→{format_utc_iso_millis(window_end)}"
        )
        for s in batch_sentences:
            print(f"  · {s.get('text', '')[:120]}")
        return None

    if client is None:
        return None

    handle = await client.start_workflow(
        TRANSCRIPT_WORKFLOW_TYPE,
        args=[batch_payload],
        id=wf_id,
        task_queue=task_queue,
    )
    print(
        f"[stt→temporal] batch #{sequence:04d} submitted  "
        f"id={wf_id}  "
        f"sentences={len(batch_sentences)}  "
        f"speaker={personne!r}",
        flush=True,
    )
    # Return a task that resolves to the workflow result dict so the caller
    # can dispatch next_sentence signals to child workflows once the next
    # batch of sentences is collected.
    return asyncio.create_task(handle.result())


# ── Main bridge loop ───────────────────────────────────────────────────────────


async def run_bridge(
    *,
    sentence_source: AsyncIterator[dict],
    client: "Client | None",
    args: argparse.Namespace,
) -> int:
    """Read sentence dicts from *sentence_source*, buffer them, flush windows to Temporal."""
    buffer: list[dict[str, Any]] = []
    window_start: datetime | None = None
    sequence = 0
    buffer_seconds = max(1.0, args.buffer_seconds)
    min_sentences = max(1, args.min_sentences)

    # Track the previous batch's result task so we can dispatch next_sentence
    # signals to its child workflows as soon as the next batch is collected.
    _prev_batch_result_task: asyncio.Task | None = None
    # Keep a strong reference to background signal tasks so they are not GC'd.
    _signal_dispatch_tasks: list[asyncio.Task] = []

    async def _flush(window_end: datetime) -> None:
        nonlocal buffer, window_start, sequence, _prev_batch_result_task
        if not buffer or window_start is None:
            return
        sequence += 1

        # ── Signal previous children with the CURRENT buffer sentences ────────
        # The sentences just collected are the speaker's "next content" for the
        # claims fact-checked in the previous batch.  We send them as a signal
        # so the reviewer agent can decide if a self-correction occurred.
        if _prev_batch_result_task is not None and client is not None:
            signal_payload = _build_next_sentence_signal(buffer)
            _dispatch = asyncio.create_task(
                _send_signals_when_result_ready(
                    _prev_batch_result_task, signal_payload, client
                )
            )
            _signal_dispatch_tasks.append(_dispatch)
            # Clean up completed signal tasks to avoid unbounded growth.
            _signal_dispatch_tasks[:] = [t for t in _signal_dispatch_tasks if not t.done()]

        # ── Submit new batch and register its result task ─────────────────────
        result_task = await submit_batch(
            client=client,
            batch_sentences=list(buffer),
            window_start=window_start,
            window_end=window_end,
            source_video=args.source_video,
            post_delay_seconds=args.video_delay_seconds,
            analysis_timeout_seconds=args.analysis_timeout_seconds,
            task_queue=args.task_queue,
            workflow_id_prefix=args.workflow_id_prefix,
            sequence=sequence,
            dry_run=args.dry_run,
        )
        # Store the result task so the NEXT flush can signal this batch's children.
        _prev_batch_result_task = result_task
        buffer = []
        window_start = None

    async for payload in sentence_source:
        sentence = normalize_sentence(payload)
        if not sentence["text"]:
            continue

        sentence_time = parse_sentence_timestamp(payload)

        if window_start is None:
            window_start = sentence_time

        buffer.append(sentence)

        # ── Flush conditions (OR-logic) ────────────────────────────────────
        elapsed = (sentence_time - window_start).total_seconds()
        should_flush_time = elapsed >= buffer_seconds
        should_flush_count = len(buffer) >= min_sentences

        if should_flush_time or should_flush_count:
            reason = "time" if should_flush_time else "count"
            print(
                f"[stt→temporal] flush ({reason}): "
                f"{len(buffer)} phrase(s), {elapsed:.1f}s écoulées",
                file=sys.stderr,
                flush=True,
            )
            await _flush(sentence_time)

    # Source exhausted — flush whatever remains in the buffer.
    if buffer and window_start is not None:
        await _flush(datetime.now(timezone.utc))

    return 0


# ── Entry-point ────────────────────────────────────────────────────────────────


async def run() -> int:
    load_workflows_env(override=False)
    args = parse_args()

    if args.input_jsonl == "-":
        input_handle: TextIO = sys.stdin
        should_close = False
    else:
        path = Path(args.input_jsonl)
        if not path.exists():
            print(f"[stt→temporal] fichier introuvable: {path}", file=sys.stderr)
            return 1
        input_handle = path.open("r", encoding="utf-8")
        should_close = True

    client: Client | None = None
    if not args.dry_run:
        client = await Client.connect(args.address, namespace=args.namespace)
        print(
            f"[stt→temporal] connecté à Temporal {args.address} "
            f"(namespace={args.namespace}, queue={args.task_queue})",
            file=sys.stderr,
            flush=True,
        )
    else:
        print("[stt→temporal] dry-run — aucune connexion Temporal", file=sys.stderr)

    print(
        f"[stt→temporal] buffer={args.buffer_seconds}s  "
        f"min_sentences={args.min_sentences}  "
        f"source={'stdin' if args.input_jsonl == '-' else args.input_jsonl}",
        file=sys.stderr,
        flush=True,
    )

    try:
        return await run_bridge(
            sentence_source=sentences_from_textio(input_handle),
            client=client,
            args=args,
        )
    finally:
        if should_close:
            input_handle.close()


def main() -> int:
    try:
        return asyncio.run(run())
    except KeyboardInterrupt:
        print("\n[stt→temporal] arrêt (Ctrl+C).", file=sys.stderr)
        return 0
    except RuntimeError as exc:
        print(f"[stt→temporal] erreur: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
