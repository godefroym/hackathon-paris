#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from temporalio import workflow

from debate_config import (
    DEFAULT_ANALYSIS_TIMEOUT_SECONDS,
    DEFAULT_POST_TIMEOUT_SECONDS,
    DEFAULT_TASK_QUEUE,
    DEFAULT_VIDEO_DELAY_SECONDS,
    WORKFLOW_TYPE,
)

ANALYZE_ACTIVITY_NAME = "analyze_debate_line"
SELF_CORRECTION_ACTIVITY_NAME = "check_next_phrase_self_correction"
POST_ACTIVITY_NAME = "post_fact_check_result"


def _claim_text_from_current_json(current_json: dict[str, Any]) -> str:
    current = current_json.get("affirmation_courante")
    if isinstance(current, str) and current.strip():
        return current.strip()
    fallback = current_json.get("affirmation")
    if isinstance(fallback, str) and fallback.strip():
        return fallback.strip()
    return ""


def _is_http_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


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


def _format_utc_iso_millis(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _normalize_sources(raw_sources: Any) -> list[dict[str, str]]:
    if not isinstance(raw_sources, list):
        return []

    collected: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for item in raw_sources:
        if not isinstance(item, dict):
            continue
        organization = item.get("organization")
        url = item.get("url")
        if not isinstance(organization, str) or not isinstance(url, str):
            continue
        org = organization.strip()
        href = url.strip()
        if not org or not href or not _is_http_url(href):
            continue
        if href in seen_urls:
            continue
        seen_urls.add(href)
        collected.append({"organization": org, "url": href})
    return collected


def _collect_sources(analysis_result: dict[str, Any]) -> list[dict[str, str]]:
    collected: list[dict[str, str]] = _normalize_sources(analysis_result.get("sources"))
    seen_urls: set[str] = {source["url"] for source in collected}

    nested_analysis = analysis_result.get("analysis")
    if isinstance(nested_analysis, dict):
        nested_sources = _normalize_sources(nested_analysis.get("sources"))
        for source in nested_sources:
            href = source["url"]
            if href in seen_urls:
                continue
            seen_urls.add(href)
            collected.append(source)

    explications = analysis_result.get("explications")
    if isinstance(explications, dict):
        for value in explications.values():
            if not isinstance(value, dict):
                continue
            source = value.get("source")
            url = value.get("url")
            if not isinstance(source, str) or not isinstance(url, str):
                continue
            org = source.strip()
            href = url.strip()
            if not org or not href or not _is_http_url(href):
                continue
            if href in seen_urls:
                continue
            seen_urls.add(href)
            collected.append({"organization": org, "url": href})

    return collected


def _summary_from_analysis_result(analysis_result: dict[str, Any]) -> str:
    ready_analysis = analysis_result.get("analysis")
    if isinstance(ready_analysis, dict):
        ready_summary = ready_analysis.get("summary")
        if isinstance(ready_summary, str) and ready_summary.strip():
            return ready_summary.strip()

    summary_parts: list[str] = []
    explications = analysis_result.get("explications")

    if isinstance(explications, dict):
        preferred_keys = ("statistique", "contexte", "coherence", "rhetorique")
        for key in preferred_keys:
            value = explications.get(key)
            if isinstance(value, dict):
                text = value.get("texte")
                if isinstance(text, str) and text.strip():
                    summary_parts.append(text.strip())
            elif isinstance(value, str) and value.strip():
                summary_parts.append(value.strip())

        if not summary_parts:
            for value in explications.values():
                if isinstance(value, dict):
                    text = value.get("texte")
                    if isinstance(text, str) and text.strip():
                        summary_parts.append(text.strip())
                elif isinstance(value, str) and value.strip():
                    summary_parts.append(value.strip())

    if summary_parts:
        return " ".join(summary_parts)

    reason = analysis_result.get("raison")
    if isinstance(reason, str) and reason.strip():
        return reason.strip()
    error = analysis_result.get("erreur")
    if isinstance(error, str) and error.strip():
        return error.strip()
    return ""


def _infer_non_postable_reason(
    current_json: dict[str, Any], analysis_result: Any
) -> str:
    if not isinstance(analysis_result, dict):
        return "analysis_not_dict"
    if not bool(analysis_result.get("afficher_bandeau", False)):
        return "afficher_bandeau_false"

    ready_claim = analysis_result.get("claim")
    ready_analysis = analysis_result.get("analysis")
    if isinstance(ready_claim, dict) and isinstance(ready_analysis, dict):
        ready_claim_text = ready_claim.get("text")
        ready_summary = ready_analysis.get("summary")
        ready_sources = ready_analysis.get("sources")
        if not (isinstance(ready_claim_text, str) and ready_claim_text.strip()):
            return "missing_claim_text"
        if not (isinstance(ready_summary, str) and ready_summary.strip()):
            return "missing_summary"
        if not isinstance(ready_sources, list):
            return "missing_sources"
        if not _normalize_sources(ready_sources):
            return "no_valid_sources"

    claim_text = _claim_text_from_current_json(current_json)
    if not claim_text:
        return "missing_claim_text"

    summary = _summary_from_analysis_result(analysis_result)
    if not summary:
        return "missing_summary"

    if not _collect_sources(analysis_result):
        return "no_valid_sources"

    return "unknown"


def _build_fact_check_api_payload(
    current_json: dict[str, Any], analysis_result: Any
) -> dict[str, Any] | None:
    if not isinstance(analysis_result, dict):
        return None

    if not bool(analysis_result.get("afficher_bandeau", False)):
        return None

    # Support Emma-style activities output that is already API-ready.
    ready_claim = analysis_result.get("claim")
    ready_analysis = analysis_result.get("analysis")
    if isinstance(ready_claim, dict) and isinstance(ready_analysis, dict):
        ready_claim_text = ready_claim.get("text")
        ready_summary = ready_analysis.get("summary")
        ready_sources = ready_analysis.get("sources")
        if (
            isinstance(ready_claim_text, str)
            and ready_claim_text.strip()
            and isinstance(ready_summary, str)
            and ready_summary.strip()
            and isinstance(ready_sources, list)
        ):
            normalized_sources = _normalize_sources(ready_sources)
            if normalized_sources:
                ready_verdict = analysis_result.get("overall_verdict")
                verdict_value = (
                    str(ready_verdict).strip()
                    if isinstance(ready_verdict, str) and ready_verdict.strip()
                    else "inconnu"
                )
                return {
                    "claim": {"text": ready_claim_text.strip()[:2000]},
                    "analysis": {
                        "summary": ready_summary.strip()[:3000],
                        "sources": normalized_sources[:8],
                    },
                    "overall_verdict": verdict_value[:100],
                }

    claim_text = _claim_text_from_current_json(current_json)
    if not claim_text:
        return None

    summary = _summary_from_analysis_result(analysis_result)
    if not summary:
        return None

    sources = _collect_sources(analysis_result)
    if not sources:
        return None

    verdict = analysis_result.get("verdict_global")
    if not isinstance(verdict, str) or not verdict.strip():
        fallback_verdict = analysis_result.get("overall_verdict")
        if isinstance(fallback_verdict, str) and fallback_verdict.strip():
            verdict = fallback_verdict.strip()
        else:
            verdict = "inconnu"

    return {
        "claim": {"text": claim_text[:2000]},
        "analysis": {
            "summary": summary[:3000],
            "sources": sources[:8],
        },
        "overall_verdict": str(verdict).strip()[:100],
    }


@workflow.defn(name=WORKFLOW_TYPE)
class DebateJsonNoopWorkflow:
    @workflow.run
    async def run(
        self,
        current_json: dict[str, Any],
        last_minute_json: dict[str, Any],
        post_delay_seconds: float = DEFAULT_VIDEO_DELAY_SECONDS,
        analysis_timeout_seconds: int = DEFAULT_ANALYSIS_TIMEOUT_SECONDS,
        next_json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # Run analysis first, then wait the remaining stream-delay time before POST.
        delay_before_post = max(0.0, float(post_delay_seconds))
        analysis_timeout = max(1, int(analysis_timeout_seconds))
        workflow.logger.info(
            "Workflow started",
            requested_delay_before_post_seconds=delay_before_post,
            analysis_timeout_seconds=analysis_timeout,
            has_current_json=True,
            has_last_minute_json=True,
            has_next_json=bool(next_json),
        )

        analysis_started = workflow.time()
        analysis_result = await workflow.execute_activity(
            ANALYZE_ACTIVITY_NAME,
            args=[current_json, last_minute_json],
            start_to_close_timeout=timedelta(seconds=analysis_timeout),
        )
        correction_check = await workflow.execute_activity(
            SELF_CORRECTION_ACTIVITY_NAME,
            args=[current_json, next_json, last_minute_json],
            start_to_close_timeout=timedelta(seconds=min(analysis_timeout, 10)),
        )
        pre_post_elapsed = max(0.0, workflow.time() - analysis_started)
        remaining_delay = max(0.0, delay_before_post - pre_post_elapsed)
        if remaining_delay > 0:
            await workflow.sleep(remaining_delay)

        skip_post_due_to_correction = False
        if isinstance(correction_check, dict):
            skip_post_due_to_correction = bool(
                correction_check.get("has_next_phrase")
                and correction_check.get("next_is_correction")
            )

        if skip_post_due_to_correction:
            post_payload = None
            reason = ""
            if isinstance(correction_check, dict):
                reason = str(correction_check.get("reason", "")).strip()
            if isinstance(analysis_result, dict):
                analysis_result = {
                    **analysis_result,
                    "afficher_bandeau": False,
                    "raison": (
                        "Fact-check ignore: phrase suivante identifiee comme correction."
                        if not reason
                        else f"Fact-check ignore: {reason}"
                    ),
                }
            post_result = {
                "posted": False,
                "skipped": True,
                "reason": "next_phrase_self_correction",
            }
        else:
            post_payload = _build_fact_check_api_payload(current_json, analysis_result)
            if post_payload is None:
                details = _infer_non_postable_reason(current_json, analysis_result)
                if isinstance(analysis_result, dict):
                    analysis_result = {
                        **analysis_result,
                        "afficher_bandeau": False,
                        "raison": f"Fact-check ignore: {details}.",
                    }
                post_result = {
                    "posted": False,
                    "skipped": True,
                    "reason": "analysis_not_postable",
                    "details": details,
                }
            else:
                post_result = await workflow.execute_activity(
                    POST_ACTIVITY_NAME,
                    args=[post_payload],
                    start_to_close_timeout=timedelta(seconds=DEFAULT_POST_TIMEOUT_SECONDS),
                )

        workflow.logger.info(
            "Workflow completed",
            pre_post_elapsed_seconds=pre_post_elapsed,
            remaining_delay_seconds=remaining_delay,
            skip_post_due_to_correction=skip_post_due_to_correction,
        )
        current_keys = sorted(current_json.keys()) if isinstance(current_json, dict) else []
        last_minute_phrases = []
        if isinstance(last_minute_json, dict):
            phrases = last_minute_json.get("phrases")
            if isinstance(phrases, list):
                last_minute_phrases = [p for p in phrases if isinstance(p, str)]

        metadata = current_json.get("metadata") if isinstance(current_json, dict) else None
        phrase_start_raw = ""
        phrase_end_raw = ""
        phrase_start_dt: datetime | None = None
        if isinstance(metadata, dict):
            phrase_start_raw = str(metadata.get("timestamp_start", "")).strip()
            phrase_end_raw = str(
                metadata.get("timestamp_end") or metadata.get("timestamp") or ""
            ).strip()
            phrase_start_dt = _parse_utc_iso(phrase_start_raw)

        target_post_dt: datetime | None = None
        if phrase_start_dt is not None:
            target_post_dt = phrase_start_dt + timedelta(seconds=delay_before_post)

        posted_at_raw = ""
        posted_at_dt: datetime | None = None
        if isinstance(post_result, dict):
            posted_at_raw = str(post_result.get("posted_at_utc", "")).strip()
            posted_at_dt = _parse_utc_iso(posted_at_raw)

        measured_delay_from_start_seconds: float | None = None
        delay_error_seconds: float | None = None
        if phrase_start_dt is not None and posted_at_dt is not None:
            measured_delay_from_start_seconds = max(
                0.0, (posted_at_dt - phrase_start_dt).total_seconds()
            )
            delay_error_seconds = measured_delay_from_start_seconds - delay_before_post

        return {
            "accepted": True,
            "requested_delay_before_post_seconds": delay_before_post,
            "analysis_timeout_seconds": analysis_timeout,
            "pre_post_elapsed_seconds": pre_post_elapsed,
            "remaining_delay_seconds": remaining_delay,
            "current_json_keys": current_keys,
            "last_minute_phrases_count": len(last_minute_phrases),
            "correction_check": correction_check,
            "skip_post_due_to_correction": skip_post_due_to_correction,
            "analysis_result": analysis_result,
            "post_payload_preview": post_payload,
            "post_result": post_result,
            "timing_debug": {
                "phrase_start_timestamp": phrase_start_raw,
                "phrase_end_timestamp": phrase_end_raw,
                "target_post_timestamp": (
                    _format_utc_iso_millis(target_post_dt) if target_post_dt else ""
                ),
                "posted_at_utc": posted_at_raw,
                "measured_delay_from_start_seconds": measured_delay_from_start_seconds,
                "delay_error_seconds": delay_error_seconds,
            },
        }
