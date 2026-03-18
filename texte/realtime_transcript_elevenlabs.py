#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, TextIO
from urllib.parse import urlencode

# Leave empty and set key in env ELEVENLABS_API_KEY if preferred.
API_KEY = ""


def load_env_from_project_root() -> Path | None:
    project_root = Path(__file__).resolve().parents[1]
    env_path = project_root / "cle.env"
    if not env_path.exists():
        return None

    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        is_quoted = len(value) >= 2 and (
            (value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")
        )
        if is_quoted:
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        os.environ[key] = value
    return env_path


LOADED_ENV_PATH = load_env_from_project_root()


def load_pyaudio():
    try:
        import pyaudio
    except ImportError as exc:
        raise RuntimeError(
            "PyAudio missing. Activate venv and run: pip install -r texte/requirements.txt"
        ) from exc
    return pyaudio


def load_websockets():
    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError(
            "websockets missing. Activate venv and run: pip install -r texte/requirements.txt"
        ) from exc
    return websockets


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
            raise RuntimeError("No default input microphone detected.") from exc
        raise RuntimeError(
            f"Invalid microphone index: {input_device_index}. "
            "Use --list-devices to see available devices."
        ) from exc
    finally:
        p.terminate()


async def iter_microphone(
    *,
    sample_rate: int,
    chunk_duration_ms: int,
    input_device_index: int | None,
) -> AsyncIterator[bytes]:
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


def emit_json_line(payload: dict[str, object], output: TextIO) -> None:
    output.write(json.dumps(payload, ensure_ascii=False) + "\n")
    output.flush()


def format_utc_iso_millis(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def build_ws_url(
    *,
    model_id: str,
    language_code: str | None,
    sample_rate: int,
    commit_strategy: str,
    include_timestamps: bool,
    include_language_detection: bool,
) -> str:
    params: dict[str, str] = {
        "model_id": model_id,
        "audio_format": f"pcm_{sample_rate}",
        "commit_strategy": commit_strategy,
        "include_timestamps": "true" if include_timestamps else "false",
        "include_language_detection": "true" if include_language_detection else "false",
    }
    if language_code:
        params["language_code"] = language_code
    return f"wss://api.elevenlabs.io/v1/speech-to-text/realtime?{urlencode(params)}"


async def connect_websocket(uri: str, api_key: str):
    websockets = load_websockets()
    base_kwargs = {
        "ping_interval": 20,
        "ping_timeout": 20,
        "close_timeout": 5,
        "max_size": 8 * 1024 * 1024,
    }
    for header_arg in ("extra_headers", "additional_headers"):
        kwargs = dict(base_kwargs)
        kwargs[header_arg] = {"xi-api-key": api_key}
        try:
            return await websockets.connect(uri, **kwargs)
        except TypeError as exc:
            if "unexpected keyword argument" in str(exc):
                continue
            raise
    raise RuntimeError("Could not open websocket: headers argument mismatch.")


async def send_audio_chunks(
    *,
    ws,
    sample_rate: int,
    chunk_duration_ms: int,
    input_device_index: int | None,
    commit_strategy: str,
    manual_commit_every_chunks: int,
) -> None:
    chunk_count = 0
    async for chunk in iter_microphone(
        sample_rate=sample_rate,
        chunk_duration_ms=chunk_duration_ms,
        input_device_index=input_device_index,
    ):
        chunk_count += 1
        payload: dict[str, object] = {
            "message_type": "input_audio_chunk",
            "audio_base_64": base64.b64encode(chunk).decode("ascii"),
            "sample_rate": sample_rate,
        }
        if commit_strategy == "manual":
            payload["commit"] = (chunk_count % manual_commit_every_chunks) == 0
        await ws.send(json.dumps(payload))


async def receive_and_export(
    *,
    ws,
    personne: str,
    question_posee: str,
    source_video: str,
    recent_window: int,
    show_partials: bool,
    output: TextIO,
) -> None:
    recent_sentences: deque[str] = deque(maxlen=recent_window)
    start_time = datetime.now(timezone.utc)

    async for raw_message in ws:
        if not isinstance(raw_message, str):
            continue
        try:
            message = json.loads(raw_message)
        except json.JSONDecodeError:
            continue

        message_type = str(message.get("message_type", "")).strip()
        if message_type == "session_started":
            print("[elevenlabs] session connected", file=sys.stderr, flush=True)
            continue

        if message_type == "partial_transcript":
            if show_partials:
                text = str(message.get("text", "")).strip()
                if text:
                    print(f"[partial] {text}", file=sys.stderr, flush=True)
            continue

        if message_type in (
            "committed_transcript",
            "committed_transcript_with_timestamps",
        ):
            sentence = str(message.get("text", "")).strip()
            if not sentence:
                continue

            now_utc = datetime.now(timezone.utc)
            recent_sentences.append(sentence)

            elapsed_seconds = int((now_utc - start_time).total_seconds())
            mm = elapsed_seconds // 60
            ss = elapsed_seconds % 60
            emit_json_line(
                {
                    "personne": personne,
                    "question_posee": question_posee,
                    "affirmation": sentence,
                    "affirmation_courante": sentence,
                    "metadata": {
                        "source_video": source_video,
                        "timestamp_elapsed": f"{mm:02d}:{ss:02d}",
                        "timestamp": format_utc_iso_millis(now_utc),
                    },
                },
                output,
            )
            continue

        if message_type.endswith("_error") or message_type == "error":
            details = str(message.get("message", "")).strip()
            if not details:
                details = json.dumps(message, ensure_ascii=False)
            raise RuntimeError(f"ElevenLabs realtime error: {details}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Realtime transcription with ElevenLabs (scribe) to JSONL "
            "(one JSON line per committed phrase)."
        )
    )
    parser.add_argument(
        "--api-key",
        default=API_KEY or os.environ.get("ELEVENLABS_API_KEY", ""),
        help="ElevenLabs API key",
    )
    parser.add_argument(
        "--model-id",
        default="scribe_v2_realtime",
        help="Realtime speech-to-text model id",
    )
    parser.add_argument(
        "--language-code",
        default="",
        help="Language code when --language-mode=fixed, e.g. fr or en",
    )
    parser.add_argument(
        "--language-mode",
        choices=["auto", "fixed"],
        default="auto",
        help="auto = multi-language detection, fixed = force --language-code",
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=16000,
        choices=[8000, 16000, 22050, 24000, 44100, 48000],
        help="Microphone sample rate in Hz",
    )
    parser.add_argument(
        "--chunk-duration-ms",
        type=int,
        default=100,
        help="Microphone chunk size in milliseconds",
    )
    parser.add_argument(
        "--commit-strategy",
        choices=["vad", "manual"],
        default="vad",
        help="Commit strategy used by ElevenLabs realtime API",
    )
    parser.add_argument(
        "--manual-commit-every-chunks",
        type=int,
        default=5,
        help="In manual mode, marks one commit every N sent chunks",
    )
    parser.add_argument(
        "--input-device-index",
        type=int,
        default=None,
        help="Input microphone index (--list-devices to inspect indexes)",
    )
    parser.add_argument(
        "--personne",
        default="",
        help="Speaker name for JSON output",
    )
    parser.add_argument(
        "--mic-name",
        default="",
        help="Fallback speaker name when --personne is empty",
    )
    parser.add_argument(
        "--question-posee",
        default="",
        help="Current question (empty if unknown)",
    )
    parser.add_argument(
        "--source-video",
        default="",
        help="Source channel/program in metadata.source_video",
    )
    parser.add_argument(
        "--recent-window",
        type=int,
        default=3,
        help="Deprecated: output now emits one committed phrase per JSON line",
    )
    parser.add_argument(
        "--show-partials",
        action="store_true",
        help="Print partial transcripts to stderr",
    )
    parser.add_argument(
        "--output-jsonl",
        default="",
        help="JSONL output file path (if empty, stdout)",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List input devices and exit",
    )
    return parser.parse_args()


async def run() -> int:
    args = parse_args()
    if args.list_devices:
        print(json.dumps(list_input_devices(), ensure_ascii=False, indent=2))
        return 0

    if not args.api_key:
        print(
            "API key missing: add ELEVENLABS_API_KEY in cle.env "
            "(repo root) or set ELEVENLABS_API_KEY.",
            file=sys.stderr,
        )
        return 1

    if args.recent_window < 1:
        print("--recent-window must be >= 1", file=sys.stderr)
        return 1

    if args.commit_strategy == "manual" and args.manual_commit_every_chunks < 1:
        print("--manual-commit-every-chunks must be >= 1", file=sys.stderr)
        return 1

    normalized_language_code = args.language_code.strip().lower()
    if args.language_mode == "fixed" and not normalized_language_code:
        print(
            "--language-mode fixed requires --language-code (example: --language-code fr)",
            file=sys.stderr,
        )
        return 1
    if args.language_mode == "auto":
        normalized_language_code = None

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

    print(f"[info] source mic: {mic_device_name}", file=sys.stderr, flush=True)
    print(f"[info] personne JSON: {personne}", file=sys.stderr, flush=True)
    if LOADED_ENV_PATH is not None:
        print(f"[info] env loaded: {LOADED_ENV_PATH}", file=sys.stderr, flush=True)
    if args.language_mode == "auto":
        print("[info] language mode: auto (multi-language detection)", file=sys.stderr, flush=True)
    else:
        print(
            f"[info] language mode: fixed ({normalized_language_code})",
            file=sys.stderr,
            flush=True,
        )

    ws_url = build_ws_url(
        model_id=args.model_id,
        language_code=normalized_language_code,
        sample_rate=args.sample_rate,
        commit_strategy=args.commit_strategy,
        include_timestamps=False,
        include_language_detection=args.language_mode == "auto",
    )

    ws = await connect_websocket(ws_url, args.api_key)
    send_task = asyncio.create_task(
        send_audio_chunks(
            ws=ws,
            sample_rate=args.sample_rate,
            chunk_duration_ms=args.chunk_duration_ms,
            input_device_index=args.input_device_index,
            commit_strategy=args.commit_strategy,
            manual_commit_every_chunks=args.manual_commit_every_chunks,
        )
    )
    receive_task = asyncio.create_task(
        receive_and_export(
            ws=ws,
            personne=personne,
            question_posee=args.question_posee,
            source_video=args.source_video,
            recent_window=args.recent_window,
            show_partials=args.show_partials,
            output=output,
        )
    )

    try:
        done, pending = await asyncio.wait(
            [send_task, receive_task], return_when=asyncio.FIRST_COMPLETED
        )
        for task in done:
            exc = task.exception()
            if exc is not None:
                raise exc
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        return 0
    finally:
        await ws.close()
        if output_file is not None:
            output_file.close()


def main() -> int:
    try:
        return asyncio.run(run())
    except KeyboardInterrupt:
        print("\nStop requested (Ctrl+C).", file=sys.stderr)
        return 0
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
