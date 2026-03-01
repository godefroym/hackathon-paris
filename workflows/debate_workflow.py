#!/usr/bin/env python3
from __future__ import annotations

from datetime import timedelta
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


def _collect_sources(analysis_result: dict[str, Any]) -> list[dict[str, str]]:
    collected: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    sources = analysis_result.get("sources")
    if isinstance(sources, list):
        for item in sources:
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


def _build_fact_check_api_payload(
    current_json: dict[str, Any], analysis_result: Any
) -> dict[str, Any] | None:
    if not isinstance(analysis_result, dict):
        return None

    if not bool(analysis_result.get("afficher_bandeau", False)):
        return None

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
                post_result = {
                    "posted": False,
                    "skipped": True,
                    "reason": "analysis_not_postable",
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
        }
