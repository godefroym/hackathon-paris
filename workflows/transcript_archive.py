from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPORTS_ROOT = Path("reports/live_transcripts")


def _slugify(value: str, fallback: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return normalized or fallback


def _parse_utc_iso(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _extract_phrase_text(current_json: dict[str, Any]) -> str:
    current = current_json.get("affirmation_courante")
    if isinstance(current, str) and current.strip():
        return current.strip()
    fallback = current_json.get("affirmation")
    if isinstance(fallback, str) and fallback.strip():
        return fallback.strip()
    return ""


def _build_session_dir(current_json: dict[str, Any]) -> tuple[str, Path]:
    metadata = current_json.get("metadata") if isinstance(current_json, dict) else None
    timestamp_raw = ""
    source_video = "source"
    if isinstance(metadata, dict):
        timestamp_raw = str(
            metadata.get("timestamp_start") or metadata.get("timestamp") or ""
        ).strip()
        source_video = str(metadata.get("source_video") or "source").strip() or "source"
    speaker = str(current_json.get("personne") or "speaker").strip() or "speaker"

    timestamp = _parse_utc_iso(timestamp_raw) or datetime.now(timezone.utc)
    session_id = (
        f"{timestamp.strftime('%Y-%m-%d')}"
        f"__{_slugify(source_video, 'source')}"
        f"__{_slugify(speaker, 'speaker')}"
    )
    return session_id, REPORTS_ROOT / session_id


def _build_entry(payload: dict[str, Any]) -> dict[str, Any]:
    current_json = payload.get("current_json")
    analysis_result = payload.get("analysis_result")
    post_result = payload.get("post_result")
    correction_check = payload.get("correction_check")

    if not isinstance(current_json, dict):
        current_json = {}
    if not isinstance(analysis_result, dict):
        analysis_result = {}
    if not isinstance(post_result, dict):
        post_result = {}
    if not isinstance(correction_check, dict):
        correction_check = {}

    metadata = current_json.get("metadata") if isinstance(current_json.get("metadata"), dict) else {}
    claim = analysis_result.get("claim") if isinstance(analysis_result.get("claim"), dict) else {}
    analysis = analysis_result.get("analysis") if isinstance(analysis_result.get("analysis"), dict) else {}
    summary = str(analysis.get("summary") or "").strip()
    sources = analysis.get("sources") if isinstance(analysis.get("sources"), list) else []

    return {
        "workflow_id": str(payload.get("workflow_id") or "").strip(),
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "speaker": str(current_json.get("personne") or "").strip(),
        "source_video": str(metadata.get("source_video") or "").strip(),
        "timestamp_start": str(metadata.get("timestamp_start") or "").strip(),
        "timestamp_end": str(metadata.get("timestamp_end") or metadata.get("timestamp") or "").strip(),
        "utterance_text": _extract_phrase_text(current_json),
        "claim_text": str(claim.get("text") or "").strip(),
        "fact_check_summary": summary,
        "overall_verdict": str(analysis_result.get("overall_verdict") or "").strip(),
        "afficher_bandeau": bool(analysis_result.get("afficher_bandeau", False)),
        "posted": bool(post_result.get("posted", False)),
        "post_reason": str(post_result.get("reason") or "").strip(),
        "correction_reason": str(correction_check.get("reason") or "").strip(),
        "sources": sources,
        "analysis_result": analysis_result,
        "post_result": post_result,
    }


def _entry_sort_key(entry: dict[str, Any]) -> tuple[str, str]:
    return (
        str(entry.get("timestamp_start") or entry.get("timestamp_end") or ""),
        str(entry.get("workflow_id") or ""),
    )


def _render_markdown(entries: list[dict[str, Any]], session_id: str) -> str:
    lines = [
        f"# Transcript Fact-Check - {session_id}",
        "",
        f"Entries: {len(entries)}",
        "",
    ]
    for index, entry in enumerate(entries, start=1):
        timestamp = str(entry.get("timestamp_start") or entry.get("timestamp_end") or "")
        speaker = str(entry.get("speaker") or "Unknown")
        utterance = str(entry.get("utterance_text") or "").strip()
        summary = str(entry.get("fact_check_summary") or "").strip() or "(aucun fact-check/context)"
        verdict = str(entry.get("overall_verdict") or "").strip() or "unverified"
        banner = "yes" if entry.get("afficher_bandeau") else "no"
        posted = "yes" if entry.get("posted") else "no"

        lines.extend(
            [
                f"## {index}. {timestamp} - {speaker}",
                "",
                f"Phrase: {utterance}",
                "",
                f"Fact-check: {summary}",
                "",
                f"Verdict: {verdict}",
                "",
                f"Bandeau: {banner}",
                "",
                f"POST API: {posted}",
            ]
        )

        sources = entry.get("sources")
        if isinstance(sources, list) and sources:
            lines.append("")
            lines.append("Sources:")
            for source in sources:
                if not isinstance(source, dict):
                    continue
                organization = str(source.get("organization") or "").strip() or "source"
                url = str(source.get("url") or "").strip()
                if url:
                    lines.append(f"- {organization}: {url}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def archive_transcript_entry_payload(payload: dict[str, Any]) -> dict[str, Any]:
    current_json = payload.get("current_json")
    if not isinstance(current_json, dict):
        return {
            "archived": False,
            "reason": "missing_current_json",
        }

    session_id, session_dir = _build_session_dir(current_json)
    entries_dir = session_dir / "entries"
    entries_dir.mkdir(parents=True, exist_ok=True)

    workflow_id = str(payload.get("workflow_id") or "").strip()
    entry_filename = _slugify(workflow_id, "entry")
    entry_path = entries_dir / f"{entry_filename}.json"
    entry = _build_entry(payload)
    entry_path.write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    entries: list[dict[str, Any]] = []
    for file_path in sorted(entries_dir.glob("*.json")):
        try:
            loaded = json.loads(file_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(loaded, dict):
            entries.append(loaded)
    entries.sort(key=_entry_sort_key)

    jsonl_path = session_dir / "transcript.jsonl"
    jsonl_lines = [json.dumps(item, ensure_ascii=False) for item in entries]
    jsonl_path.write_text(("\n".join(jsonl_lines) + "\n") if jsonl_lines else "", encoding="utf-8")

    markdown_path = session_dir / "transcript.md"
    markdown_path.write_text(_render_markdown(entries, session_id), encoding="utf-8")

    return {
        "archived": True,
        "session_id": session_id,
        "session_dir": str(session_dir),
        "entry_path": str(entry_path),
        "jsonl_path": str(jsonl_path),
        "markdown_path": str(markdown_path),
        "entries_count": len(entries),
    }
