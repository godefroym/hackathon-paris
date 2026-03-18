#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import base64
import difflib
import json
import os
import re
import sys
import unicodedata
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncIterator, TextIO
from urllib.parse import urlencode

from mistralai import Mistral
from mistralai.extra.realtime import UnknownRealtimeEvent
from mistralai.models import (
    AudioFormat,
    RealtimeTranscriptionError,
    RealtimeTranscriptionSessionCreated,
    TranscriptionStreamDone,
    TranscriptionStreamTextDelta,
)

# Leave empty and set via env if preferred.
MISTRAL_API_KEY = ""
ELEVENLABS_API_KEY = ""


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


@dataclass
class CandidateUtterance:
    provider: str
    text: str
    start_timestamp: datetime | None
    timestamp: datetime


@dataclass
class ProviderClosed:
    provider: str


def load_pyaudio():
    try:
        import pyaudio
    except ImportError as exc:
        raise RuntimeError(
            "PyAudio missing. Activate venv then install requirements."
        ) from exc
    return pyaudio


def load_websockets():
    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError(
            "websockets missing. Activate venv then install requirements."
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
            "Use --list-devices to inspect available devices."
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


async def queue_audio_iter(queue: asyncio.Queue[bytes | None]) -> AsyncIterator[bytes]:
    while True:
        chunk = await queue.get()
        if chunk is None:
            return
        yield chunk


async def broadcast_microphone(
    *,
    sample_rate: int,
    chunk_duration_ms: int,
    input_device_index: int | None,
    queues: list[asyncio.Queue[bytes | None]],
) -> None:
    try:
        async for chunk in iter_microphone(
            sample_rate=sample_rate,
            chunk_duration_ms=chunk_duration_ms,
            input_device_index=input_device_index,
        ):
            for q in queues:
                try:
                    q.put_nowait(chunk)
                except asyncio.QueueFull:
                    # Keep most recent audio when a downstream provider is reconnecting.
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    try:
                        q.put_nowait(chunk)
                    except asyncio.QueueFull:
                        pass
    finally:
        for q in queues:
            while True:
                try:
                    q.put_nowait(None)
                    break
                except asyncio.QueueFull:
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        break


def split_complete_sentences(text: str) -> tuple[list[str], str]:
    complete: list[str] = []
    start = 0
    for idx, char in enumerate(text):
        if char in ".!?\n":
            sentence = text[start : idx + 1].strip()
            if sentence:
                complete.append(sentence)
            start = idx + 1
    return complete, text[start:]


def format_utc_iso_millis(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def emit_json_line(payload: dict[str, object], output: TextIO) -> None:
    output.write(json.dumps(payload, ensure_ascii=False) + "\n")
    output.flush()


def normalize_text(text: str) -> str:
    lowered = text.lower().strip()
    lowered = re.sub(r"\s+", " ", lowered)
    lowered = re.sub(r"[^\w\s]", "", lowered)
    return lowered.strip()


def similarity_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(a=a, b=b).ratio()


def latin_ratio(text: str) -> float:
    total_letters = 0
    latin_letters = 0
    for ch in text:
        if not ch.isalpha():
            continue
        total_letters += 1
        try:
            if "LATIN" in unicodedata.name(ch):
                latin_letters += 1
        except ValueError:
            continue
    if total_letters == 0:
        return 1.0
    return latin_letters / total_letters


def choose_by_heuristic(
    text_a: str,
    text_b: str,
    *,
    prefer: str,
    prefer_latin_script: bool,
) -> tuple[str, str]:
    norm_a = normalize_text(text_a)
    norm_b = normalize_text(text_b)
    if not norm_a and norm_b:
        return "b", text_b
    if not norm_b and norm_a:
        return "a", text_a
    if prefer_latin_script:
        lat_a = latin_ratio(text_a)
        lat_b = latin_ratio(text_b)
        if lat_a >= 0.60 and lat_b < 0.40:
            return "a", text_a
        if lat_b >= 0.60 and lat_a < 0.40:
            return "b", text_b
    if norm_a == norm_b:
        return ("a", text_a) if prefer == "a" else ("b", text_b)
    if norm_a in norm_b:
        # Prefer conservative transcript when one strictly contains the other.
        return "a", text_a
    if norm_b in norm_a:
        return "b", text_b
    return ("a", text_a) if prefer == "a" else ("b", text_b)


def extract_message_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        fragments: list[str] = []
        for item in content:
            if isinstance(item, str):
                fragments.append(item)
            elif isinstance(item, dict):
                text_value = item.get("text")
                if isinstance(text_value, str):
                    fragments.append(text_value)
        return "".join(fragments)
    return str(content)


def word_count(text: str) -> int:
    return len(re.findall(r"\w+", text, flags=re.UNICODE))


def estimate_phrase_duration_seconds(text: str) -> float:
    words = max(1, word_count(text))
    return max(0.7, min(8.0, words / 2.8))


CLEANUP_STOPWORDS = {
    "a",
    "ai",
    "as",
    "au",
    "aux",
    "ce",
    "cela",
    "ces",
    "cette",
    "dans",
    "de",
    "des",
    "du",
    "elle",
    "elles",
    "en",
    "est",
    "et",
    "il",
    "ils",
    "je",
    "la",
    "le",
    "les",
    "leur",
    "lui",
    "mais",
    "mes",
    "mon",
    "nous",
    "on",
    "ou",
    "pas",
    "pour",
    "que",
    "qui",
    "sa",
    "se",
    "ses",
    "son",
    "sur",
    "ta",
    "te",
    "tes",
    "toi",
    "tu",
    "un",
    "une",
    "vos",
    "votre",
    "vous",
}

_NON_PROPER_CAPITALIZED = {
    "La",
    "Le",
    "Les",
    "Un",
    "Une",
    "Des",
    "Du",
    "De",
    "Je",
    "Tu",
    "Il",
    "Elle",
    "Ils",
    "Elles",
    "Nous",
    "Vous",
    "On",
    "Et",
    "Mais",
    "Donc",
    "Car",
    "Puis",
    "Oui",
    "Non",
    "Ah",
    "Oh",
    "Pardon",
}


def extract_numbers(text: str) -> list[str]:
    if not isinstance(text, str):
        return []
    return re.findall(r"\d+(?:[.,]\d+)?", text)


def extract_keyword_tokens(text: str) -> set[str]:
    tokens = re.findall(r"[a-zA-ZÀ-ÿ0-9]+", text.lower())
    return {
        token
        for token in tokens
        if len(token) >= 4 and token not in CLEANUP_STOPWORDS
    }


def extract_named_tokens(text: str) -> set[str]:
    named: set[str] = set()
    for token in re.findall(r"\b[A-ZÀ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'-]{1,}\b", text):
        if token in _NON_PROPER_CAPITALIZED:
            continue
        named.add(token.lower())
    for token in re.findall(r"\b[A-Z]{2,}\b", text):
        named.add(token.lower())
    return named


def guard_cleaned_sentence(
    *,
    original_text: str,
    cleaned_text: str,
    mode: str,
    confidence: float,
) -> tuple[str, str]:
    original = original_text.strip()
    cleaned = cleaned_text.strip()
    if not cleaned:
        return original, "cleanup_rejected_empty"

    norm_original = normalize_text(original)
    norm_cleaned = normalize_text(cleaned)
    if not norm_cleaned:
        return original, "cleanup_rejected_empty_normalized"
    if norm_cleaned == norm_original:
        return original, "cleanup_no_change"

    similarity = similarity_ratio(norm_original, norm_cleaned)
    orig_words = max(1, word_count(original))
    clean_words = max(1, word_count(cleaned))
    orig_numbers = extract_numbers(original)
    clean_numbers = extract_numbers(cleaned)
    if orig_numbers != clean_numbers and (orig_numbers or clean_numbers):
        return original, "cleanup_rejected_numbers_changed"

    orig_named = extract_named_tokens(original)
    clean_named = extract_named_tokens(cleaned)
    if orig_named:
        missing_named = orig_named - clean_named
        extra_named = clean_named - orig_named
        if missing_named:
            return original, "cleanup_rejected_named_entity_removed"
        if extra_named:
            return original, "cleanup_rejected_named_entity_added"

    orig_keywords = extract_keyword_tokens(original)
    clean_keywords = extract_keyword_tokens(cleaned)
    keyword_overlap = (
        len(orig_keywords & clean_keywords) / len(orig_keywords)
        if orig_keywords
        else 1.0
    )
    substituted_keywords = bool((orig_keywords - clean_keywords) and (clean_keywords - orig_keywords))

    if clean_words > (orig_words * 3 + 6):
        return original, f"cleanup_rejected_too_long_{clean_words}_{orig_words}"
    if clean_words < max(1, orig_words // 3):
        return original, f"cleanup_rejected_too_short_{clean_words}_{orig_words}"

    if mode == "conservative":
        if substituted_keywords:
            return original, "cleanup_rejected_conservative_keyword_substitution"
        if keyword_overlap < 0.80:
            return original, f"cleanup_rejected_conservative_keyword_overlap_{keyword_overlap:.2f}"
        if similarity >= 0.92 and clean_words <= (orig_words + 2):
            return cleaned, f"cleanup_applied_conservative_sim_{similarity:.2f}"
        if confidence >= 0.96 and similarity >= 0.85 and clean_words <= (orig_words + 2):
            return cleaned, f"cleanup_applied_conservative_conf_{confidence:.2f}_sim_{similarity:.2f}"
        return original, f"cleanup_rejected_conservative_sim_{similarity:.2f}_conf_{confidence:.2f}_kw_{keyword_overlap:.2f}"

    if mode == "aggressive":
        if substituted_keywords and not (confidence >= 0.97 and similarity >= 0.92):
            return original, "cleanup_rejected_aggressive_keyword_substitution"
        if keyword_overlap < 0.65:
            return original, f"cleanup_rejected_aggressive_keyword_overlap_{keyword_overlap:.2f}"
        if confidence >= 0.85 and similarity >= 0.70:
            return cleaned, f"cleanup_applied_aggressive_conf_{confidence:.2f}_sim_{similarity:.2f}"
        if similarity >= 0.90 and clean_words <= (orig_words + 4):
            return cleaned, f"cleanup_applied_aggressive_sim_{similarity:.2f}"
        return original, f"cleanup_rejected_aggressive_sim_{similarity:.2f}_conf_{confidence:.2f}_kw_{keyword_overlap:.2f}"

    return original, "cleanup_mode_none"


async def judge_with_llm(
    *,
    client: Mistral,
    model: str,
    context_sentences: list[str],
    mistral_text: str,
    elevenlabs_text: str,
    timeout_seconds: float,
) -> tuple[str, str, str]:
    context_block = "\n".join(f"- {s}" for s in context_sentences) if context_sentences else "- (none)"
    prompt = (
        "You are a transcription arbiter.\n"
        "Choose the better candidate between two realtime transcripts of the same spoken sentence.\n"
        "Rules:\n"
        "1) Keep the language spoken by the speaker (no translation).\n"
        "2) Prefer grammatical and semantically coherent sentence.\n"
        "3) Do NOT hallucinate or add content not likely spoken.\n"
        "4) Penalize obvious script errors/gibberish.\n"
        "5) If both are equivalent, prefer the conservative candidate (usually shorter).\n"
        "Return strict JSON with keys: winner, final_text, reason.\n"
        "winner must be one of: mistral, elevenlabs.\n\n"
        f"Recent context:\n{context_block}\n\n"
        f'Mistral candidate: "{mistral_text}"\n'
        f'ElevenLabs candidate: "{elevenlabs_text}"\n'
    )

    async def _call():
        return await client.chat.complete_async(
            model=model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
        )

    response = await asyncio.wait_for(_call(), timeout=timeout_seconds)
    choice = response.choices[0].message
    content_text = extract_message_text(choice.content)
    data = json.loads(content_text)
    winner = str(data.get("winner", "")).strip().lower()
    final_text = str(data.get("final_text", "")).strip()
    reason = str(data.get("reason", "")).strip()

    if winner not in {"mistral", "elevenlabs"}:
        raise RuntimeError(f"Invalid LLM winner: {winner!r}")
    if not final_text:
        final_text = mistral_text if winner == "mistral" else elevenlabs_text
    return winner, final_text, reason


async def cleanup_sentence_with_llm(
    *,
    client: Mistral,
    model: str,
    context_sentences: list[str],
    chosen_text: str,
    mistral_text: str,
    elevenlabs_text: str,
    timeout_seconds: float,
    mode: str,
) -> tuple[str, float, str]:
    context_block = "\n".join(f"- {s}" for s in context_sentences) if context_sentences else "- (none)"
    prompt = (
        "You are an ASR sentence cleaner.\n"
        "Goal: return one cleaned sentence for realtime subtitles/fact-check.\n"
        "Rules:\n"
        "1) Keep the spoken language; never translate.\n"
        "2) Keep the speaker meaning, do not add new facts.\n"
        "3) Fix obvious ASR artifacts, broken words, and punctuation.\n"
        "4) NEVER replace person names, organization names, country/city names, or numeric values.\n"
        "5) Prefer concise, natural phrasing.\n"
        "6) If uncertain, keep chosen_text unchanged.\n"
        f"Mode: {mode}\n"
        "Return strict JSON keys: cleaned_text, confidence, reason.\n\n"
        f"Recent context:\n{context_block}\n\n"
        f'Chosen text: "{chosen_text}"\n'
        f'Mistral candidate: "{mistral_text}"\n'
        f'ElevenLabs candidate: "{elevenlabs_text}"\n'
    )

    async def _call():
        return await client.chat.complete_async(
            model=model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
        )

    response = await asyncio.wait_for(_call(), timeout=timeout_seconds)
    choice = response.choices[0].message
    content_text = extract_message_text(choice.content)
    data = json.loads(content_text)
    cleaned_text = str(data.get("cleaned_text", "")).strip()
    reason = str(data.get("reason", "")).strip()
    try:
        confidence = float(data.get("confidence", 0))
    except Exception:
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    return cleaned_text, confidence, reason


async def choose_fused_sentence(
    *,
    mistral_candidate: CandidateUtterance,
    elevenlabs_candidate: CandidateUtterance,
    recent_context: list[str],
    llm_client: Mistral | None,
    judge_model: str,
    llm_similarity_threshold: float,
    llm_timeout_seconds: float,
    preferred_provider: str,
    prefer_latin_script: bool,
) -> tuple[str, str, str]:
    mistral_text = mistral_candidate.text.strip()
    eleven_text = elevenlabs_candidate.text.strip()
    norm_m = normalize_text(mistral_text)
    norm_e = normalize_text(eleven_text)

    if not norm_m and norm_e:
        return "elevenlabs", eleven_text, "empty_mistral"
    if not norm_e and norm_m:
        return "mistral", mistral_text, "empty_elevenlabs"
    if not norm_m and not norm_e:
        return "mistral", mistral_text, "both_empty"

    if prefer_latin_script:
        lat_m = latin_ratio(mistral_text)
        lat_e = latin_ratio(eleven_text)
        if lat_m >= 0.60 and lat_e < 0.40:
            return "mistral", mistral_text, f"latin_script_guard_mistral_{lat_m:.2f}_{lat_e:.2f}"
        if lat_e >= 0.60 and lat_m < 0.40:
            return "elevenlabs", eleven_text, f"latin_script_guard_eleven_{lat_m:.2f}_{lat_e:.2f}"

    prefer_key = "a" if preferred_provider == "mistral" else "b"
    ratio = similarity_ratio(norm_m, norm_e)
    if ratio >= llm_similarity_threshold:
        pick, text = choose_by_heuristic(
            mistral_text,
            eleven_text,
            prefer=prefer_key,
            prefer_latin_script=prefer_latin_script,
        )
        return ("mistral", text, f"heuristic_similar_{ratio:.2f}") if pick == "a" else (
            "elevenlabs",
            text,
            f"heuristic_similar_{ratio:.2f}",
        )

    if llm_client is None:
        pick, text = choose_by_heuristic(
            mistral_text,
            eleven_text,
            prefer=prefer_key,
            prefer_latin_script=prefer_latin_script,
        )
        return ("mistral", text, "heuristic_no_llm") if pick == "a" else (
            "elevenlabs",
            text,
            "heuristic_no_llm",
        )

    try:
        winner, final_text, reason = await judge_with_llm(
            client=llm_client,
            model=judge_model,
            context_sentences=recent_context,
            mistral_text=mistral_text,
            elevenlabs_text=eleven_text,
            timeout_seconds=llm_timeout_seconds,
        )
        return winner, final_text, f"llm:{reason}" if reason else "llm"
    except Exception as exc:
        pick, text = choose_by_heuristic(
            mistral_text,
            eleven_text,
            prefer=prefer_key,
            prefer_latin_script=prefer_latin_script,
        )
        fallback_reason = f"heuristic_after_llm_error:{type(exc).__name__}"
        return ("mistral", text, fallback_reason) if pick == "a" else (
            "elevenlabs",
            text,
            fallback_reason,
        )


async def run_mistral_stream(
    *,
    client: Mistral,
    model: str,
    delay_ms: int,
    sample_rate: int,
    audio_stream: AsyncIterator[bytes],
    events: asyncio.Queue[CandidateUtterance | ProviderClosed],
) -> None:
    def is_recoverable_stream_error(exc: Exception) -> bool:
        message = str(exc).lower()
        recoverable_markers = (
            "enginedeaderror",
            "grpc streaming transcription error",
            "statuscode.unknown",
            "status 500",
            "service unavailable",
            "connection reset",
            "timed out",
        )
        return any(marker in message for marker in recoverable_markers)

    pending = ""
    pending_start: datetime | None = None
    full_text = ""
    audio_format = AudioFormat(encoding="pcm_s16le", sample_rate=sample_rate)
    start_compensation = timedelta(milliseconds=max(0, int(delay_ms)))
    reconnect_attempt = 0
    max_reconnect_attempts = 8
    try:
        while True:
            try:
                async for event in client.audio.realtime.transcribe_stream(
                    audio_stream=audio_stream,
                    model=model,
                    audio_format=audio_format,
                    target_streaming_delay_ms=delay_ms,
                ):
                    if isinstance(event, RealtimeTranscriptionSessionCreated):
                        reconnect_attempt = 0
                        print("[mistral] session connected", file=sys.stderr, flush=True)
                        continue
                    if isinstance(event, TranscriptionStreamTextDelta):
                        event_time = datetime.now(timezone.utc)
                        full_text += event.text
                        if pending_start is None and event.text.strip():
                            pending_start = event_time - start_compensation
                        pending += event.text
                        complete_sentences, pending = split_complete_sentences(pending)
                        for sentence in complete_sentences:
                            sentence_start = pending_start or (event_time - start_compensation)
                            duration_based_start = event_time - timedelta(
                                seconds=estimate_phrase_duration_seconds(sentence)
                            )
                            if duration_based_start < sentence_start:
                                sentence_start = duration_based_start
                            await events.put(
                                CandidateUtterance(
                                    provider="mistral",
                                    text=sentence,
                                    start_timestamp=sentence_start,
                                    timestamp=event_time,
                                )
                            )
                            pending_start = event_time - start_compensation
                        if not pending.strip():
                            pending_start = None
                        continue
                    if isinstance(event, TranscriptionStreamDone):
                        return
                    if isinstance(event, RealtimeTranscriptionError):
                        raise RuntimeError(f"Mistral realtime error: {event.error}")
                    if isinstance(event, UnknownRealtimeEvent):
                        continue
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not is_recoverable_stream_error(exc) or reconnect_attempt >= max_reconnect_attempts:
                    raise RuntimeError(f"Mistral realtime error: {exc}") from exc
                reconnect_attempt += 1
                backoff_seconds = min(8.0, 0.8 * (2 ** (reconnect_attempt - 1)))
                jitter = random.uniform(0.0, 0.35)
                wait_seconds = backoff_seconds + jitter
                print(
                    "[mistral] stream error; reconnecting "
                    f"(attempt {reconnect_attempt}/{max_reconnect_attempts}) in {wait_seconds:.2f}s: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
                await asyncio.sleep(wait_seconds)
    finally:
        await events.put(ProviderClosed(provider="mistral"))


def build_elevenlabs_ws_url(
    *,
    model_id: str,
    language_code: str | None,
    sample_rate: int,
    commit_strategy: str,
    include_language_detection: bool,
) -> str:
    params: dict[str, str] = {
        "model_id": model_id,
        "audio_format": f"pcm_{sample_rate}",
        "commit_strategy": commit_strategy,
        "include_timestamps": "false",
        "include_language_detection": "true" if include_language_detection else "false",
    }
    if language_code:
        params["language_code"] = language_code
    return f"wss://api.elevenlabs.io/v1/speech-to-text/realtime?{urlencode(params)}"


async def connect_elevenlabs_ws(uri: str, api_key: str):
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
    raise RuntimeError("Cannot open ElevenLabs websocket: headers argument mismatch.")


async def run_elevenlabs_stream(
    *,
    api_key: str,
    ws_url: str,
    audio_stream: AsyncIterator[bytes],
    sample_rate: int,
    commit_strategy: str,
    manual_commit_every_chunks: int,
    events: asyncio.Queue[CandidateUtterance | ProviderClosed],
    show_partials: bool,
) -> None:
    ws = await connect_elevenlabs_ws(ws_url, api_key)

    async def sender() -> None:
        chunk_count = 0
        async for chunk in audio_stream:
            chunk_count += 1
            payload: dict[str, object] = {
                "message_type": "input_audio_chunk",
                "audio_base_64": base64.b64encode(chunk).decode("ascii"),
                "sample_rate": sample_rate,
            }
            if commit_strategy == "manual":
                payload["commit"] = (chunk_count % manual_commit_every_chunks) == 0
            await ws.send(json.dumps(payload))

    async def receiver() -> None:
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
                    partial = str(message.get("text", "")).strip()
                    if partial:
                        print(f"[elevenlabs][partial] {partial}", file=sys.stderr, flush=True)
                continue
            if message_type in (
                "committed_transcript",
                "committed_transcript_with_timestamps",
            ):
                text = str(message.get("text", "")).strip()
                if not text:
                    continue
                event_time = datetime.now(timezone.utc)
                estimated_duration_seconds = estimate_phrase_duration_seconds(text)
                await events.put(
                    CandidateUtterance(
                        provider="elevenlabs",
                        text=text,
                        start_timestamp=event_time
                        - timedelta(seconds=estimated_duration_seconds),
                        timestamp=event_time,
                    )
                )
                continue
            if message_type.endswith("_error") or message_type == "error":
                details = str(message.get("message", "")).strip()
                if not details:
                    details = json.dumps(message, ensure_ascii=False)
                raise RuntimeError(f"ElevenLabs realtime error: {details}")

    tasks = [asyncio.create_task(sender()), asyncio.create_task(receiver())]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in done:
            exc = task.exception()
            if exc is not None:
                raise exc
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await ws.close()
        await events.put(ProviderClosed(provider="elevenlabs"))


def pending_has_items(pending: dict[str, deque[CandidateUtterance]]) -> bool:
    return any(len(queue) > 0 for queue in pending.values())


async def fusion_export_loop(
    *,
    events: asyncio.Queue[CandidateUtterance | ProviderClosed],
    output: TextIO,
    personne: str,
    question_posee: str,
    source_video: str,
    pipeline_language: str,
    recent_window: int,
    active_providers: set[str],
    pair_max_skew_seconds: float,
    pair_min_similarity: float,
    solo_wait_seconds: float,
    dedupe_window_seconds: float,
    llm_client: Mistral | None,
    judge_model: str,
    llm_similarity_threshold: float,
    llm_timeout_seconds: float,
    preferred_provider: str,
    prefer_latin_script: bool,
    cleanup_mode: str,
    cleanup_model: str,
    cleanup_timeout_seconds: float,
    show_decisions: bool,
) -> None:
    start_time = datetime.now(timezone.utc)
    pending: dict[str, deque[CandidateUtterance]] = {
        provider: deque() for provider in active_providers
    }
    closed_providers: set[str] = set()
    fused_recent_sentences: deque[str] = deque(maxlen=recent_window)
    recent_emits: deque[tuple[datetime, str]] = deque(maxlen=20)

    async def emit_sentence(
        sentence: str,
        ts: datetime,
        phrase_start_ts: datetime | None,
        provider: str,
        reason: str,
        mistral_text: str,
        elevenlabs_text: str,
    ) -> None:
        final_sentence = sentence.strip()
        cleanup_reason = ""

        if cleanup_mode != "none" and llm_client is not None and final_sentence:
            try:
                cleaned_text, confidence, llm_cleanup_reason = await cleanup_sentence_with_llm(
                    client=llm_client,
                    model=cleanup_model,
                    context_sentences=list(fused_recent_sentences),
                    chosen_text=final_sentence,
                    mistral_text=mistral_text,
                    elevenlabs_text=elevenlabs_text,
                    timeout_seconds=cleanup_timeout_seconds,
                    mode=cleanup_mode,
                )
                final_sentence, guard_reason = guard_cleaned_sentence(
                    original_text=final_sentence,
                    cleaned_text=cleaned_text,
                    mode=cleanup_mode,
                    confidence=confidence,
                )
                cleanup_reason = guard_reason
                if llm_cleanup_reason:
                    cleanup_reason = f"{cleanup_reason}:{llm_cleanup_reason}"
            except Exception as exc:
                cleanup_reason = f"cleanup_error:{type(exc).__name__}"

        normalized = normalize_text(final_sentence)
        if normalized:
            for prev_ts, prev_norm in reversed(recent_emits):
                if (ts - prev_ts).total_seconds() > dedupe_window_seconds:
                    break
                if prev_norm == normalized:
                    if show_decisions:
                        print(
                            f"[fusion] dropped_duplicate provider={provider} reason={reason} sentence={final_sentence}",
                            file=sys.stderr,
                            flush=True,
                        )
                    return
        fused_recent_sentences.append(final_sentence)
        if normalized:
            recent_emits.append((ts, normalized))
        start_ts = phrase_start_ts or ts
        if start_ts > ts:
            start_ts = ts
        elapsed_seconds = int((start_ts - start_time).total_seconds())
        mm = elapsed_seconds // 60
        ss = elapsed_seconds % 60
        payload = {
            "personne": personne,
            "question_posee": question_posee,
            "affirmation": final_sentence,
            "affirmation_courante": final_sentence,
            "metadata": {
                "source_video": source_video,
                "pipeline_language": pipeline_language,
                "timestamp_elapsed": f"{mm:02d}:{ss:02d}",
                "timestamp_start": format_utc_iso_millis(start_ts),
                "timestamp_end": format_utc_iso_millis(ts),
                # Backward-compatible key: keep "timestamp" as the phrase end.
                "timestamp": format_utc_iso_millis(ts),
            },
        }
        emit_json_line(payload, output)
        if show_decisions:
            suffix = f" cleanup={cleanup_reason}" if cleanup_reason else ""
            print(
                f"[fusion] provider={provider} reason={reason}{suffix} sentence={final_sentence}",
                file=sys.stderr,
                flush=True,
            )

    async def process_pending(now: datetime) -> None:
        if active_providers == {"mistral", "elevenlabs"}:
            while pending["mistral"] and pending["elevenlabs"]:
                m = pending["mistral"][0]
                e = pending["elevenlabs"][0]
                skew = (m.timestamp - e.timestamp).total_seconds()
                sim = similarity_ratio(normalize_text(m.text), normalize_text(e.text))
                if abs(skew) <= pair_max_skew_seconds or sim >= pair_min_similarity:
                    pending["mistral"].popleft()
                    pending["elevenlabs"].popleft()
                    winner, sentence, reason = await choose_fused_sentence(
                        mistral_candidate=m,
                        elevenlabs_candidate=e,
                        recent_context=list(fused_recent_sentences),
                        llm_client=llm_client,
                        judge_model=judge_model,
                        llm_similarity_threshold=llm_similarity_threshold,
                        llm_timeout_seconds=llm_timeout_seconds,
                        preferred_provider=preferred_provider,
                        prefer_latin_script=prefer_latin_script,
                    )
                    ts = m.timestamp if m.timestamp >= e.timestamp else e.timestamp
                    candidate_starts = [
                        c for c in (m.start_timestamp, e.start_timestamp) if c is not None
                    ]
                    phrase_start_ts = min(candidate_starts) if candidate_starts else None
                    await emit_sentence(
                        sentence,
                        ts,
                        phrase_start_ts,
                        winner,
                        reason,
                        m.text,
                        e.text,
                    )
                    continue

                if skew < -pair_max_skew_seconds:
                    age = (now - m.timestamp).total_seconds()
                    if age < solo_wait_seconds:
                        break
                    pending["mistral"].popleft()
                    await emit_sentence(
                        m.text,
                        m.timestamp,
                        m.start_timestamp,
                        "mistral",
                        "solo_timeout",
                        m.text,
                        "",
                    )
                    continue

                if skew > pair_max_skew_seconds:
                    age = (now - e.timestamp).total_seconds()
                    if age < solo_wait_seconds:
                        break
                    pending["elevenlabs"].popleft()
                    await emit_sentence(
                        e.text,
                        e.timestamp,
                        e.start_timestamp,
                        "elevenlabs",
                        "solo_timeout",
                        "",
                        e.text,
                    )
                    continue

                break

        for provider in list(active_providers):
            while pending[provider]:
                item = pending[provider][0]
                other_providers = active_providers - {provider}
                if other_providers and not other_providers.issubset(closed_providers):
                    age = (now - item.timestamp).total_seconds()
                    if age < solo_wait_seconds:
                        break
                pending[provider].popleft()
                reason = "solo_other_closed" if other_providers.issubset(closed_providers) else "solo_timeout"
                if provider == "mistral":
                    await emit_sentence(
                        item.text,
                        item.timestamp,
                        item.start_timestamp,
                        provider,
                        reason,
                        item.text,
                        "",
                    )
                else:
                    await emit_sentence(
                        item.text,
                        item.timestamp,
                        item.start_timestamp,
                        provider,
                        reason,
                        "",
                        item.text,
                    )

    while True:
        now = datetime.now(timezone.utc)
        try:
            event = await asyncio.wait_for(events.get(), timeout=0.20)
        except asyncio.TimeoutError:
            event = None

        if isinstance(event, CandidateUtterance):
            pending[event.provider].append(event)
        elif isinstance(event, ProviderClosed):
            closed_providers.add(event.provider)

        await process_pending(now=datetime.now(timezone.utc))

        if closed_providers == active_providers and not pending_has_items(pending):
            return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Realtime STT pipeline (Mistral-only): emits one JSON line per phrase."
        )
    )
    parser.add_argument(
        "--pipeline-language",
        default=os.environ.get("PIPELINE_LANGUAGE", "fr"),
        help="Pipeline language (fr|en): expected transcription language and downstream output language",
    )
    parser.add_argument(
        "--providers",
        choices=["both", "mistral", "elevenlabs"],
        default="mistral",
        help="Transcription providers to run",
    )
    parser.add_argument(
        "--mistral-api-key",
        default=MISTRAL_API_KEY or os.environ.get("MISTRAL_API_KEY", ""),
        help="Mistral API key",
    )
    parser.add_argument(
        "--elevenlabs-api-key",
        default=ELEVENLABS_API_KEY or os.environ.get("ELEVENLABS_API_KEY", ""),
        help="ElevenLabs API key",
    )
    parser.add_argument(
        "--mistral-transcribe-model",
        default="voxtral-mini-transcribe-realtime-2602",
        help="Mistral realtime transcription model",
    )
    parser.add_argument(
        "--mistral-delay-ms",
        type=int,
        default=2400,
        help="Mistral target streaming delay",
    )
    parser.add_argument(
        "--eleven-model-id",
        default="scribe_v2_realtime",
        help="ElevenLabs realtime STT model id",
    )
    parser.add_argument(
        "--language-mode",
        choices=["auto", "fixed"],
        default="auto",
        help="ElevenLabs language mode",
    )
    parser.add_argument(
        "--language-code",
        default="",
        help="ElevenLabs language code used when --language-mode=fixed",
    )
    parser.add_argument(
        "--eleven-commit-strategy",
        choices=["vad", "manual"],
        default="vad",
        help="ElevenLabs commit strategy",
    )
    parser.add_argument(
        "--eleven-manual-commit-every-chunks",
        type=int,
        default=5,
        help="In manual mode, commit every N chunks",
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=16000,
        choices=[8000, 16000, 22050, 24000, 44100, 48000],
        help="Microphone sample rate",
    )
    parser.add_argument(
        "--chunk-duration-ms",
        type=int,
        default=480,
        help="Microphone chunk size in milliseconds",
    )
    parser.add_argument(
        "--input-device-index",
        type=int,
        default=None,
        help="Input microphone index (--list-devices to inspect)",
    )
    parser.add_argument(
        "--mic-name",
        default="",
        help="Fallback speaker name if --personne is empty",
    )
    parser.add_argument(
        "--personne",
        default="",
        help="Speaker name for output JSON",
    )
    parser.add_argument(
        "--question-posee",
        default="",
        help="Current question, empty if unknown",
    )
    parser.add_argument(
        "--source-video",
        default="",
        help="metadata.source_video",
    )
    parser.add_argument(
        "--recent-window",
        type=int,
        default=3,
        help="How many recent fused phrases are kept for internal arbitration context",
    )
    parser.add_argument(
        "--pair-max-skew-seconds",
        type=float,
        default=3.0,
        help="Max timestamp skew to consider candidates from both providers as same phrase",
    )
    parser.add_argument(
        "--pair-min-similarity",
        type=float,
        default=0.60,
        help="If normalized text similarity >= this threshold, pair candidates even with timestamp skew",
    )
    parser.add_argument(
        "--solo-wait-seconds",
        type=float,
        default=3.5,
        help="Wait before emitting one provider alone when the other has no match",
    )
    parser.add_argument(
        "--dedupe-window-seconds",
        type=float,
        default=7.0,
        help="Drop duplicated emitted sentences within this time window",
    )
    parser.add_argument(
        "--disable-llm-judge",
        action="store_true",
        help="Disable LLM tie-break (use heuristic only)",
    )
    parser.add_argument(
        "--judge-model",
        default="mistral-small-latest",
        help="Mistral model used by arbitration judge",
    )
    parser.add_argument(
        "--preferred-provider",
        choices=["mistral", "elevenlabs"],
        default="mistral",
        help="Provider favored by heuristics when ambiguity remains",
    )
    parser.add_argument(
        "--disable-latin-script-guard",
        action="store_true",
        help="Disable guard that rejects obvious non-Latin script glitches when competitor is Latin",
    )
    parser.add_argument(
        "--llm-similarity-threshold",
        type=float,
        default=0.78,
        help="If normalized similarity >= threshold, skip LLM and use heuristic",
    )
    parser.add_argument(
        "--llm-timeout-seconds",
        type=float,
        default=8.0,
        help="Timeout for each LLM judge call",
    )
    parser.add_argument(
        "--cleanup-mode",
        choices=["none", "conservative", "aggressive"],
        default="conservative",
        help="Post-clean each emitted sentence with LLM",
    )
    parser.add_argument(
        "--cleanup-model",
        default="mistral-small-latest",
        help="Mistral model used for sentence cleanup",
    )
    parser.add_argument(
        "--cleanup-timeout-seconds",
        type=float,
        default=6.0,
        help="Timeout for each sentence cleanup call",
    )
    parser.add_argument(
        "--show-partials",
        action="store_true",
        help="Show ElevenLabs partial transcript logs in stderr",
    )
    parser.add_argument(
        "--show-decisions",
        action="store_true",
        help="Print fusion decision logs in stderr",
    )
    parser.add_argument(
        "--output-jsonl",
        default="",
        help="Output file path (if empty, stdout)",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List microphone input devices and exit",
    )
    return parser.parse_args()


async def run() -> int:
    args = parse_args()
    if args.list_devices:
        print(json.dumps(list_input_devices(), ensure_ascii=False, indent=2))
        return 0

    pipeline_language = args.pipeline_language.strip().lower()
    if pipeline_language not in {"fr", "en"}:
        print("--pipeline-language must be one of: fr, en", file=sys.stderr)
        return 1

    if args.recent_window < 1:
        print("--recent-window must be >= 1", file=sys.stderr)
        return 1
    if args.eleven_commit_strategy == "manual" and args.eleven_manual_commit_every_chunks < 1:
        print("--eleven-manual-commit-every-chunks must be >= 1", file=sys.stderr)
        return 1
    if args.pair_max_skew_seconds < 0:
        print("--pair-max-skew-seconds must be >= 0", file=sys.stderr)
        return 1
    if args.pair_min_similarity < 0 or args.pair_min_similarity > 1:
        print("--pair-min-similarity must be between 0 and 1", file=sys.stderr)
        return 1
    if args.solo_wait_seconds < 0:
        print("--solo-wait-seconds must be >= 0", file=sys.stderr)
        return 1
    if args.dedupe_window_seconds < 0:
        print("--dedupe-window-seconds must be >= 0", file=sys.stderr)
        return 1
    if args.cleanup_timeout_seconds <= 0:
        print("--cleanup-timeout-seconds must be > 0", file=sys.stderr)
        return 1

    if args.providers != "mistral":
        print(
            f"[info] ElevenLabs disabled for stability: forcing providers=mistral "
            f"(requested={args.providers})",
            file=sys.stderr,
            flush=True,
        )
    args.providers = "mistral"
    active_providers: set[str] = {"mistral"}

    mistral_key = args.mistral_api_key.strip()
    use_llm_cleanup = args.cleanup_mode != "none"

    if "mistral" in active_providers and not mistral_key:
        print(
            "Missing Mistral API key: add MISTRAL_API_KEY in cle.env "
            "(repo root) or pass --mistral-api-key.",
            file=sys.stderr,
        )
        return 1
    if use_llm_cleanup and not mistral_key:
        print(
            "--cleanup-mode requires MISTRAL_API_KEY in cle.env or --mistral-api-key.",
            file=sys.stderr,
        )
        return 1
    language_code = args.language_code.strip().lower()
    if args.language_mode == "fixed" and not language_code:
        language_code = pipeline_language
    if args.language_mode == "fixed" and not language_code and "elevenlabs" in active_providers:
        print("--language-mode fixed requires --language-code.", file=sys.stderr)
        return 1
    if args.language_mode == "auto":
        language_code = None

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
    print(
        f"[info] providers: {', '.join(sorted(active_providers))}",
        file=sys.stderr,
        flush=True,
    )
    print(
        f"[info] pipeline language: {pipeline_language}",
        file=sys.stderr,
        flush=True,
    )
    print(
        "[info] mistral realtime SDK has no explicit language parameter; "
        "language control is applied downstream via PIPELINE_LANGUAGE.",
        file=sys.stderr,
        flush=True,
    )
    if LOADED_ENV_PATH is not None:
        print(f"[info] env loaded: {LOADED_ENV_PATH}", file=sys.stderr, flush=True)
    print(
        f"[info] heuristic preference: {args.preferred_provider}",
        file=sys.stderr,
        flush=True,
    )
    print(
        f"[info] cleanup mode: {args.cleanup_mode}",
        file=sys.stderr,
        flush=True,
    )

    events: asyncio.Queue[CandidateUtterance | ProviderClosed] = asyncio.Queue(maxsize=200)
    tasks: list[asyncio.Task] = []
    audio_queues: list[asyncio.Queue[bytes | None]] = []

    mistral_client: Mistral | None = None
    judge_client: Mistral | None = None
    if "mistral" in active_providers:
        mistral_client = Mistral(api_key=mistral_key)

    use_llm_judge = not args.disable_llm_judge and args.providers == "both" and bool(mistral_key)
    if use_llm_judge or use_llm_cleanup:
        judge_client = Mistral(api_key=mistral_key)

    if "mistral" in active_providers:
        mistral_queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=50)
        audio_queues.append(mistral_queue)
        tasks.append(
            asyncio.create_task(
                run_mistral_stream(
                    client=mistral_client,
                    model=args.mistral_transcribe_model,
                    delay_ms=args.mistral_delay_ms,
                    sample_rate=args.sample_rate,
                    audio_stream=queue_audio_iter(mistral_queue),
                    events=events,
                )
            )
        )

    if "elevenlabs" in active_providers:
        eleven_queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=50)
        audio_queues.append(eleven_queue)
        ws_url = build_elevenlabs_ws_url(
            model_id=args.eleven_model_id,
            language_code=language_code,
            sample_rate=args.sample_rate,
            commit_strategy=args.eleven_commit_strategy,
            include_language_detection=args.language_mode == "auto",
        )
        tasks.append(
            asyncio.create_task(
                run_elevenlabs_stream(
                    api_key=eleven_key,
                    ws_url=ws_url,
                    audio_stream=queue_audio_iter(eleven_queue),
                    sample_rate=args.sample_rate,
                    commit_strategy=args.eleven_commit_strategy,
                    manual_commit_every_chunks=args.eleven_manual_commit_every_chunks,
                    events=events,
                    show_partials=args.show_partials,
                )
            )
        )

    tasks.append(
        asyncio.create_task(
            broadcast_microphone(
                sample_rate=args.sample_rate,
                chunk_duration_ms=args.chunk_duration_ms,
                input_device_index=args.input_device_index,
                queues=audio_queues,
            )
        )
    )
    tasks.append(
        asyncio.create_task(
            fusion_export_loop(
                events=events,
                output=output,
                personne=personne,
                question_posee=args.question_posee,
                source_video=args.source_video,
                pipeline_language=pipeline_language,
                recent_window=args.recent_window,
                active_providers=active_providers,
                pair_max_skew_seconds=args.pair_max_skew_seconds,
                pair_min_similarity=args.pair_min_similarity,
                solo_wait_seconds=args.solo_wait_seconds,
                dedupe_window_seconds=args.dedupe_window_seconds,
                llm_client=judge_client,
                judge_model=args.judge_model,
                llm_similarity_threshold=args.llm_similarity_threshold,
                llm_timeout_seconds=args.llm_timeout_seconds,
                preferred_provider=args.preferred_provider,
                prefer_latin_script=not args.disable_latin_script_guard,
                cleanup_mode=args.cleanup_mode,
                cleanup_model=args.cleanup_model,
                cleanup_timeout_seconds=args.cleanup_timeout_seconds,
                show_decisions=args.show_decisions,
            )
        )
    )

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
        print("\nStop requested (Ctrl+C).", file=sys.stderr)
        return 0
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
