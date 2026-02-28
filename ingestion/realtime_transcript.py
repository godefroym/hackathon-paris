#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import AsyncIterator, Sequence, TextIO

from mistralai import Mistral
from mistralai.extra.realtime import UnknownRealtimeEvent
from mistralai.models import (
    AudioFormat,
    RealtimeTranscriptionError,
    RealtimeTranscriptionSessionCreated,
    TranscriptionStreamDone,
    TranscriptionStreamTextDelta,
)

# Laisse vide et remplis ta cle ici si tu ne veux pas utiliser MISTRAL_API_KEY.
API_KEY = ""


@dataclass
class StreamState:
    fast_full_text: str = ""
    slow_full_text: str = ""


def load_pyaudio():
    try:
        import pyaudio
    except ImportError as exc:
        raise RuntimeError(
            "PyAudio manquant. Active le venv puis lance `pip install -r requirements.txt`."
        ) from exc
    return pyaudio


def list_input_devices() -> list[dict[str, object]]:
    pyaudio = load_pyaudio()
    p = pyaudio.PyAudio()
    devices: list[dict[str, object]] = []
    try:
        for index in range(p.get_device_count()):
            info = p.get_device_info_by_index(index)
            if int(info.get("maxInputChannels", 0)) <= 0:
                continue
            devices.append(
                {
                    "index": index,
                    "name": str(info.get("name", "")),
                    "max_input_channels": int(info.get("maxInputChannels", 0)),
                    "default_sample_rate": int(info.get("defaultSampleRate", 0)),
                }
            )
    finally:
        p.terminate()
    return devices


def resolve_input_device_name(input_device_index: int | None) -> str:
    pyaudio = load_pyaudio()
    p = pyaudio.PyAudio()
    try:
        if input_device_index is None:
            info = p.get_default_input_device_info()
        else:
            info = p.get_device_info_by_index(input_device_index)
        return str(info.get("name", "unknown-input-device"))
    except OSError as exc:
        if input_device_index is None:
            raise RuntimeError("Aucun micro d'entree par defaut detecte.") from exc
        raise RuntimeError(
            f"Index de micro invalide: {input_device_index}. "
            "Utilise `--list-devices` pour voir les micros disponibles."
        ) from exc
    finally:
        p.terminate()


async def iter_microphone(
    *,
    sample_rate: int,
    chunk_duration_ms: int,
    input_device_index: int | None,
) -> AsyncIterator[bytes]:
    """Yield microphone PCM chunks (16-bit mono, pcm_s16le)."""
    pyaudio = load_pyaudio()
    p = pyaudio.PyAudio()
    chunk_samples = int(sample_rate * chunk_duration_ms / 1000)
    open_kwargs: dict[str, object] = {
        "format": pyaudio.paInt16,
        "channels": 1,
        "rate": sample_rate,
        "input": True,
        "frames_per_buffer": chunk_samples,
    }
    if input_device_index is not None:
        open_kwargs["input_device_index"] = input_device_index

    stream = p.open(**open_kwargs)
    loop = asyncio.get_running_loop()
    try:
        while True:
            data = await loop.run_in_executor(None, stream.read, chunk_samples, False)
            yield data
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()


async def queue_audio_iter(queue: asyncio.Queue[bytes | None]) -> AsyncIterator[bytes]:
    while True:
        chunk = await queue.get()
        if chunk is None:
            break
        yield chunk


async def broadcast_microphone(
    *,
    sample_rate: int,
    chunk_duration_ms: int,
    input_device_index: int | None,
    queues: Sequence[asyncio.Queue[bytes | None]],
) -> None:
    try:
        async for chunk in iter_microphone(
            sample_rate=sample_rate,
            chunk_duration_ms=chunk_duration_ms,
            input_device_index=input_device_index,
        ):
            for queue in queues:
                await queue.put(chunk)
    finally:
        for queue in queues:
            while True:
                try:
                    queue.put_nowait(None)
                    break
                except asyncio.QueueFull:
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break


def split_complete_sentences(text: str) -> tuple[list[str], str]:
    """Split on sentence endings (.?! or newline), return (complete, remainder)."""
    complete: list[str] = []
    start = 0
    for idx, char in enumerate(text):
        if char in ".!?\n":
            sentence = text[start : idx + 1].strip()
            if sentence:
                complete.append(sentence)
            start = idx + 1
    return complete, text[start:]


def emit_json_line(payload: dict[str, object], output: TextIO) -> None:
    output.write(json.dumps(payload, ensure_ascii=False) + "\n")
    output.flush()


def format_utc_iso_millis(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


async def run_stream(
    *,
    client: Mistral,
    model: str,
    delay_ms: int,
    audio_stream: AsyncIterator[bytes],
    audio_format: AudioFormat,
    state: StreamState,
    updates: asyncio.Queue[None],
    is_fast: bool,
    show_fast_preview: bool,
) -> None:
    async for event in client.audio.realtime.transcribe_stream(
        audio_stream=audio_stream,
        model=model,
        audio_format=audio_format,
        target_streaming_delay_ms=delay_ms,
    ):
        if isinstance(event, RealtimeTranscriptionSessionCreated):
            lane = "fast" if is_fast else "slow"
            print(
                f"[{lane}] session connectee ({delay_ms}ms)",
                file=sys.stderr,
                flush=True,
            )
        elif isinstance(event, TranscriptionStreamTextDelta):
            if is_fast:
                state.fast_full_text += event.text
                if show_fast_preview and event.text:
                    print(event.text, end="", file=sys.stderr, flush=True)
            else:
                state.slow_full_text += event.text
                if updates.empty():
                    updates.put_nowait(None)
        elif isinstance(event, TranscriptionStreamDone):
            return
        elif isinstance(event, RealtimeTranscriptionError):
            raise RuntimeError(str(event.error))
        elif isinstance(event, UnknownRealtimeEvent):
            continue


async def json_export_loop(
    *,
    personne: str,
    question_posee: str,
    source_video: str,
    state: StreamState,
    updates: asyncio.Queue[None],
    recent_window: int,
    output: TextIO,
) -> None:
    consumed = 0
    pending = ""
    recent_sentences = deque(maxlen=recent_window)
    start_time = datetime.now(timezone.utc)

    while True:
        await updates.get()
        if consumed >= len(state.slow_full_text):
            continue

        new_text = state.slow_full_text[consumed:]
        consumed = len(state.slow_full_text)
        pending += new_text

        complete_sentences, pending = split_complete_sentences(pending)
        for sentence in complete_sentences:
            now_utc = datetime.now(timezone.utc)
            recent_sentences.append(sentence)
            delta = now_utc - start_time
            total_seconds = int(delta.total_seconds())
            mm = total_seconds // 60
            ss = total_seconds % 60
            merged_affirmation = " ".join(recent_sentences)
            emit_json_line(
                {
                    "personne": personne,
                    "question_posee": question_posee,
                    "affirmation": merged_affirmation,
                    "affirmation_courante": sentence,
                    "metadata": {
                        "source_video": source_video,
                        # Keep relative timer for display if needed.
                        "timestamp_elapsed": f"{mm:02d}:{ss:02d}",
                        # Precise timestamp used for downstream temporal windows.
                        "timestamp": format_utc_iso_millis(now_utc),
                    },
                },
                output,
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Transcription realtime dual-delay (Mistral) vers JSONL "
            "(une ligne JSON par phrase complete)."
        )
    )
    parser.add_argument(
        "--api-key",
        default=API_KEY or os.environ.get("MISTRAL_API_KEY", ""),
        help="Mistral API key",
    )
    parser.add_argument(
        "--transcribe-model",
        default="voxtral-mini-transcribe-realtime-2602",
        help="Model de transcription realtime",
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=16000,
        choices=[8000, 16000, 22050, 44100, 48000],
        help="Frequence audio micro (Hz)",
    )
    parser.add_argument(
        "--chunk-duration-ms",
        type=int,
        default=20,
        help="Taille chunk micro en ms",
    )
    parser.add_argument(
        "--fast-delay-ms",
        type=int,
        default=240,
        help="Delai stream rapide (ms)",
    )
    parser.add_argument(
        "--slow-delay-ms",
        type=int,
        default=2400,
        help="Delai stream stable (ms)",
    )
    parser.add_argument(
        "--input-device-index",
        type=int,
        default=None,
        help="Index du micro d'entree (utilise --list-devices pour trouver l'index)",
    )
    parser.add_argument(
        "--mic-name",
        default="",
        help=(
            "Nom de micro / identifiant locuteur. Utilise comme fallback de `personne` "
            "si --personne n'est pas fourni."
        ),
    )
    parser.add_argument(
        "--personne",
        default="",
        help="Nom de la personne qui parle (champ JSON `personne`)",
    )
    parser.add_argument(
        "--question-posee",
        default="",
        help="Question en cours (champ JSON `question_posee`), vide si inconnue",
    )
    parser.add_argument(
        "--source-video",
        default="",
        help="Source du flux (champ JSON metadata.source_video)",
    )
    parser.add_argument(
        "--recent-window",
        type=int,
        default=3,
        help="Nombre de phrases completes recentes fusionnees dans `affirmation`",
    )
    parser.add_argument(
        "--output-jsonl",
        default="",
        help="Fichier JSONL de sortie (si vide: stdout)",
    )
    parser.add_argument(
        "--hide-fast-preview",
        action="store_true",
        help="Masquer la transcription brute du stream rapide (stderr)",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="Lister les micros d'entree et quitter",
    )
    return parser.parse_args()


async def run() -> int:
    args = parse_args()
    if args.list_devices:
        print(json.dumps(list_input_devices(), ensure_ascii=False, indent=2))
        return 0

    if not args.api_key:
        print(
            "API key manquante: remplis `API_KEY = \"...\"` dans le script "
            "ou exporte MISTRAL_API_KEY.",
            file=sys.stderr,
        )
        return 1

    if args.recent_window < 1:
        print("--recent-window doit etre >= 1", file=sys.stderr)
        return 1

    mic_device_name = resolve_input_device_name(args.input_device_index)
    mic_name = args.mic_name or mic_device_name
    personne = args.personne or mic_name

    output: TextIO
    output_file: TextIO | None = None
    if args.output_jsonl:
        output_file = open(args.output_jsonl, "a", encoding="utf-8", buffering=1)
        output = output_file
    else:
        output = sys.stdout

    print(
        f"[info] source micro: {mic_device_name}",
        file=sys.stderr,
        flush=True,
    )
    print(
        f"[info] personne JSON: {personne}",
        file=sys.stderr,
        flush=True,
    )

    client = Mistral(api_key=args.api_key)
    audio_format = AudioFormat(encoding="pcm_s16le", sample_rate=args.sample_rate)
    state = StreamState()

    fast_queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=50)
    slow_queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=50)
    updates: asyncio.Queue[None] = asyncio.Queue(maxsize=1)

    broadcaster = asyncio.create_task(
        broadcast_microphone(
            sample_rate=args.sample_rate,
            chunk_duration_ms=args.chunk_duration_ms,
            input_device_index=args.input_device_index,
            queues=(fast_queue, slow_queue),
        )
    )
    fast_task = asyncio.create_task(
        run_stream(
            client=client,
            model=args.transcribe_model,
            delay_ms=args.fast_delay_ms,
            audio_stream=queue_audio_iter(fast_queue),
            audio_format=audio_format,
            state=state,
            updates=updates,
            is_fast=True,
            show_fast_preview=not args.hide_fast_preview,
        )
    )
    slow_task = asyncio.create_task(
        run_stream(
            client=client,
            model=args.transcribe_model,
            delay_ms=args.slow_delay_ms,
            audio_stream=queue_audio_iter(slow_queue),
            audio_format=audio_format,
            state=state,
            updates=updates,
            is_fast=False,
            show_fast_preview=False,
        )
    )
    export_task = asyncio.create_task(
        json_export_loop(
            personne=personne,
            question_posee=args.question_posee,
            source_video=args.source_video,
            state=state,
            updates=updates,
            recent_window=args.recent_window,
            output=output,
        )
    )

    tasks = [broadcaster, fast_task, slow_task, export_task]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in done:
            exc = task.exception()
            if exc is not None:
                raise exc
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
        print("\nArret demande (Ctrl+C).", file=sys.stderr)
        return 0
    except RuntimeError as exc:
        print(f"Erreur: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
