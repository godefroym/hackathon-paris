#!/usr/bin/env python3
"""Unified live fact-check pipeline entrypoint.

Connects the Voxtral real-time STT to the Temporal ingestion layer in a single
process — no Unix pipe, no JSON serialization round-trip between scripts.

Architecture
------------
                    asyncio.Queue[dict | None]  (maxsize=200)
  ┌──────────────────────────┐        │       ┌──────────────────────────────┐
  │  produce_sentences()     │ ──push─┤       │  run_bridge()  (batch mode)  │
  │  realtime_transcript.py  │        └─pull─▶│  stt_to_temporal.py          │
  │                          │   or           │                              │
  │  mic → Voxtral → dicts   │        └─pull─▶│  run_per_sentence_bridge()   │
  └──────────────────────────┘                │  utils/ingestion.py          │
                                              └──────────────────────────────┘
                                                          │
                                                    Temporal client
                                                          │
                                           TranscriptBatchWorkflow  (batch)
                                           DebateJsonNoopWorkflow   (per-sentence)

Submission modes
----------------
  batch (default)
      Accumulates ~20 s of sentences → one TranscriptBatchWorkflow per window.
      Includes claim extraction and fan-out to DebateJsonNoopWorkflow × N.

  per-sentence
      Submits one DebateJsonNoopWorkflow directly per sentence.
      Equivalent to the older workers/debate_jsonl_to_temporal.py script.

Usage — live mic (most common)
-------------------------------
    uv run python pipeline.py \\
        --personne "Valérie Pécresse" \\
        --source-video "TF1 20h" \\
        --question-posee "Quelle est votre position sur l'immigration ?"

Usage — file replay (no mic)
-----------------------------
    uv run python pipeline.py \\
        --input-jsonl /path/to/recording.jsonl \\
        --dry-run

Usage — list audio input devices
---------------------------------
    uv run python pipeline.py --list-devices
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

# Allow running from the repo root or workflows/ directly.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from temporalio.client import Client

from debate_config import (
    DEFAULT_ANALYSIS_TIMEOUT_SECONDS,
    DEFAULT_STT_BUFFER_SECONDS,
    DEFAULT_STT_MIN_SENTENCES,
    DEFAULT_TASK_QUEUE,
    DEFAULT_VIDEO_DELAY_SECONDS,
    TRANSCRIPT_TASK_QUEUE,
)
from utils.env import load_workflows_env
from utils.ingestion import run_per_sentence_bridge
from realtime_transcript import list_input_devices, produce_sentences, resolve_input_device_name
from stt_to_temporal import run_bridge, sentences_from_textio, sentences_from_queue


# ── CLI ────────────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Pipeline live: micro → Voxtral STT → Temporal workflows "
            "(mode batch ou per-sentence)."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # ── Source ──────────────────────────────────────────────────────────────
    src = parser.add_argument_group("Source (mic or file)")
    src.add_argument(
        "--input-jsonl",
        default="",
        help=(
            "Fichier JSONL de replay (pas de micro). "
            "Laisser vide pour utiliser le micro en direct."
        ),
    )
    src.add_argument(
        "--input-device-index",
        type=int,
        default=None,
        help="Index du micro d'entrée (voir --list-devices).",
    )
    src.add_argument(
        "--list-devices",
        action="store_true",
        help="Lister les micros disponibles et quitter.",
    )

    # ── Speaker / context ────────────────────────────────────────────────────
    ctx = parser.add_argument_group("Speaker / context")
    ctx.add_argument(
        "--personne",
        default="",
        help="Nom du locuteur (champ JSON personne).",
    )
    ctx.add_argument(
        "--mic-name",
        default="",
        help="Fallback de --personne si non fourni.",
    )
    ctx.add_argument(
        "--question-posee",
        default="",
        help="Question en cours (champ JSON question_posee).",
    )
    ctx.add_argument(
        "--source-video",
        default=os.environ.get("SOURCE_VIDEO", ""),
        help="Identifiant du flux vidéo.",
    )

    # ── STT (Voxtral) ────────────────────────────────────────────────────────
    stt = parser.add_argument_group("STT / Voxtral")
    stt.add_argument(
        "--api-key",
        default=os.environ.get("MISTRAL_API_KEY", ""),
        help="Mistral API key (défaut: env MISTRAL_API_KEY).",
    )
    stt.add_argument(
        "--transcribe-model",
        default="voxtral-mini-transcribe-realtime-2602",
        help="Modèle Voxtral realtime.",
    )
    stt.add_argument(
        "--sample-rate",
        type=int,
        default=16000,
        choices=[8000, 16000, 22050, 44100, 48000],
        help="Fréquence audio (Hz).",
    )
    stt.add_argument(
        "--chunk-duration-ms",
        type=int,
        default=20,
        help="Durée chunk micro (ms).",
    )
    stt.add_argument(
        "--slow-delay-ms",
        type=int,
        default=2400,
        help="Délai stream Voxtral (ms).",
    )
    stt.add_argument(
        "--recent-window",
        type=int,
        default=3,
        help="Nb de phrases récentes dans le champ affirmation.",
    )
    stt.add_argument(
        "--output-jsonl",
        default="",
        help="Fichier log JSONL pour les phrases STT (optionnel).",
    )

    # ── Temporal ─────────────────────────────────────────────────────────────
    tmp = parser.add_argument_group("Temporal")
    tmp.add_argument(
        "--address",
        default="localhost:7233",
        help="Adresse Temporal frontend.",
    )
    tmp.add_argument(
        "--namespace",
        default="default",
        help="Namespace Temporal.",
    )
    tmp.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche les batches / phrases sans soumettre à Temporal.",
    )

    # ── Ingestion mode ───────────────────────────────────────────────────────
    mode = parser.add_argument_group("Ingestion mode")
    mode.add_argument(
        "--submission-mode",
        choices=["batch", "per-sentence"],
        default="batch",
        help=(
            "batch: accumule ~20 s → TranscriptBatchWorkflow (défaut). "
            "per-sentence: 1 DebateJsonNoopWorkflow par phrase."
        ),
    )

    # ── Batch mode knobs (ignored in per-sentence mode) ──────────────────────
    batch = parser.add_argument_group("Batch mode knobs")
    batch.add_argument(
        "--buffer-seconds",
        type=float,
        default=float(os.environ.get("STT_BUFFER_SECONDS", DEFAULT_STT_BUFFER_SECONDS)),
        help="Durée fenêtre d'accumulation (s).",
    )
    batch.add_argument(
        "--min-sentences",
        type=int,
        default=int(os.environ.get("STT_MIN_SENTENCES", DEFAULT_STT_MIN_SENTENCES)),
        help="Flush anticipé après N phrases.",
    )
    batch.add_argument(
        "--task-queue",
        default=TRANSCRIPT_TASK_QUEUE,
        help=f"Task queue pour TranscriptBatchWorkflow.",
    )
    batch.add_argument(
        "--workflow-id-prefix",
        default="transcript-batch",
        help="Préfixe des workflow IDs.",
    )

    # ── Per-sentence mode knobs (ignored in batch mode) ──────────────────────
    ps = parser.add_argument_group("Per-sentence mode knobs")
    ps.add_argument(
        "--per-sentence-task-queue",
        default=DEFAULT_TASK_QUEUE,
        help=f"Task queue pour DebateJsonNoopWorkflow.",
    )
    ps.add_argument(
        "--per-sentence-workflow-id-prefix",
        default="debate-line",
        help="Préfixe des workflow IDs per-sentence.",
    )

    # ── Shared timing knobs ───────────────────────────────────────────────────
    timing = parser.add_argument_group("Timing")
    timing.add_argument(
        "--video-delay-seconds",
        type=float,
        default=float(os.environ.get("VIDEO_STREAM_DELAY_SECONDS", DEFAULT_VIDEO_DELAY_SECONDS)),
        help="Délai vidéo transmis aux workflows enfants (s).",
    )
    timing.add_argument(
        "--analysis-timeout-seconds",
        type=int,
        default=int(
            os.environ.get("FACT_CHECK_ANALYSIS_TIMEOUT_SECONDS", DEFAULT_ANALYSIS_TIMEOUT_SECONDS)
        ),
        help="Timeout activité d'analyse (s).",
    )

    # ── Debug ──────────────────────────────────────────────────────────────────
    dbg = parser.add_argument_group("Debug")
    dbg.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Affiche chaque phrase STT dans la console au fur et à mesure.",
    )

    return parser.parse_args()


# ── Debug helpers ────────────────────────────────────────────────────────────


async def _debug_sentences(source: Any, label: str = "sentence") -> Any:
    """Transparent async-generator wrapper that logs each sentence to stderr."""
    async for sentence in source:
        if sentence is not None:
            print(
                f"[pipeline][debug] {label}: {json.dumps(sentence, ensure_ascii=False)}",
                file=sys.stderr,
                flush=True,
            )
        yield sentence


# ── Bridge arg adapters ───────────────────────────────────────────────────────


class _BatchBridgeArgs:
    """Minimal attribute bag expected by stt_to_temporal.run_bridge()."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.buffer_seconds: float = args.buffer_seconds
        self.min_sentences: int = args.min_sentences
        self.video_delay_seconds: float = args.video_delay_seconds
        self.analysis_timeout_seconds: int = args.analysis_timeout_seconds
        self.source_video: str = args.source_video
        self.task_queue: str = args.task_queue
        self.workflow_id_prefix: str = args.workflow_id_prefix
        self.dry_run: bool = args.dry_run


class _PerSentenceArgs:
    """Minimal attribute bag expected by utils/ingestion.run_per_sentence_bridge()."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.task_queue: str = args.per_sentence_task_queue
        self.workflow_id_prefix: str = args.per_sentence_workflow_id_prefix
        self.video_delay_seconds: float = args.video_delay_seconds
        self.analysis_timeout_seconds: int = args.analysis_timeout_seconds
        self.dry_run: bool = args.dry_run


# ── Main runner ───────────────────────────────────────────────────────────────


async def run() -> int:
    load_workflows_env(override=False)
    args = parse_args()

    # ── Early exits ──────────────────────────────────────────────────────────
    if args.list_devices:
        print(json.dumps(list_input_devices(), ensure_ascii=False, indent=2))
        return 0

    file_replay = bool(args.input_jsonl)

    if not file_replay:
        api_key = args.api_key
        if not api_key:
            print(
                "[pipeline] API key manquante: exporte MISTRAL_API_KEY ou utilise --api-key.",
                file=sys.stderr,
            )
            return 1

    # ── Connect Temporal ──────────────────────────────────────────────────────
    client: Client | None = None
    if not args.dry_run:
        client = await Client.connect(args.address, namespace=args.namespace)
        print(
            f"[pipeline] connecté à Temporal {args.address} (namespace={args.namespace})",
            file=sys.stderr,
            flush=True,
        )
    else:
        print("[pipeline] dry-run — aucune connexion Temporal", file=sys.stderr)

    # ── Resolve speaker name ──────────────────────────────────────────────────
    if not file_replay:
        mic_device_name = resolve_input_device_name(args.input_device_index)
        mic_name = args.mic_name or mic_device_name
        personne = args.personne or mic_name
        print(f"[pipeline] micro: {mic_device_name}", file=sys.stderr, flush=True)
        print(f"[pipeline] personne: {personne}", file=sys.stderr, flush=True)
    else:
        personne = args.personne

    print(
        f"[pipeline] mode={args.submission_mode}  "
        f"source={'fichier:' + args.input_jsonl if file_replay else 'micro'}",
        file=sys.stderr,
        flush=True,
    )

    # ── Choose bridge ─────────────────────────────────────────────────────────
    if args.submission_mode == "batch":
        bridge_args = _BatchBridgeArgs(args)

        async def _bridge(source: Any) -> int:
            return await run_bridge(
                sentence_source=source,
                client=client,
                args=bridge_args,
            )
    else:
        ps_args = _PerSentenceArgs(args)

        async def _bridge(source: Any) -> int:  # type: ignore[misc]
            return await run_per_sentence_bridge(
                sentence_source=source,
                client=client,
                args=ps_args,
            )

    # ── File replay mode (no mic) ─────────────────────────────────────────────
    if file_replay:
        path = Path(args.input_jsonl)
        if not path.exists():
            print(f"[pipeline] fichier introuvable: {path}", file=sys.stderr)
            return 1
        fh = path.open("r", encoding="utf-8")
        try:
            source = sentences_from_textio(fh)
            if args.debug:
                source = _debug_sentences(source, label="replay")
            return await _bridge(source)
        finally:
            fh.close()

    # ── Live mic mode (in-process queue) ──────────────────────────────────────
    output_file = None
    if args.output_jsonl:
        output_file = open(args.output_jsonl, "a", encoding="utf-8", buffering=1)

    sentence_queue: asyncio.Queue[dict | None] = asyncio.Queue(maxsize=200)

    stt_task = asyncio.create_task(
        produce_sentences(
            api_key=api_key,
            transcribe_model=args.transcribe_model,
            sample_rate=args.sample_rate,
            chunk_duration_ms=args.chunk_duration_ms,
            slow_delay_ms=args.slow_delay_ms,
            input_device_index=args.input_device_index,
            personne=personne,
            question_posee=args.question_posee,
            source_video=args.source_video,
            recent_window=args.recent_window,
            sentence_queue=sentence_queue,
            output=output_file,
        )
    )

    live_source: Any = sentences_from_queue(sentence_queue)
    if args.debug:
        live_source = _debug_sentences(live_source, label="mic")

    bridge_task = asyncio.create_task(
        _bridge(live_source)
    )

    tasks = [stt_task, bridge_task]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in done:
            exc = task.exception()
            if exc is not None:
                raise exc
        # Wait for the bridge to drain any remaining sentences.
        await asyncio.gather(*tasks)
        return 0
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if output_file is not None:
            output_file.close()


def main() -> int:
    try:
        return asyncio.run(run())
    except KeyboardInterrupt:
        print("\n[pipeline] arrêt (Ctrl+C).", file=sys.stderr)
        return 0
    except RuntimeError as exc:
        print(f"[pipeline] erreur: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
