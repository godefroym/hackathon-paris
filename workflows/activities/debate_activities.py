import copy
import os
import json
import asyncio
import re
import sys
from pathlib import Path
from typing import Any

import requests
from temporalio import activity
from temporalio.exceptions import ApplicationError
from mistralai import Mistral

# Allow direct execution: `python activities/debate_activities.py`
if __package__ in {None, ""}:
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

from utils.env import load_workflows_env
from utils.sources import domain_to_organization, is_valid_http_url
from utils.text import extract_affirmation

from activities.mistral_runtime import (
    RuntimeConfig,
    create_agent_pool,
    delete_agent_pool,
    run_task,
)
from activities.prompts import (
    build_claim_extraction_prompt,
    build_contexte_prompt,
    build_coherence_prompt,
    build_editor_prompt,
    build_rhetorique_prompt,
    build_routeur_prompt,
    build_self_correction_prompt,
    build_stat_prompt,
    get_political_profile,
)
from activities.schemas import AgentPool, ClaimExtractionOutput, ExtractedClaim, TranscriptSentence
from debate_config import DEFAULT_FACT_CHECK_POST_URL, DEFAULT_VERISTRAL_POST_URL

# Charge l'environnement local du sous-projet workflows (workflows/.env).
# OS-level variables take precedence over the .env file (override=False).
env_path = load_workflows_env(override=False)

_api_key = os.getenv("MISTRAL_API_KEY")
if not _api_key:
    raise RuntimeError(
        f"MISTRAL_API_KEY is missing or empty. "
        f"Copy {env_path.parent / '.env.example'} to {env_path} and set your key."
    )

client = Mistral(api_key=_api_key)

SOCIAL_BLACKLIST = ["tiktok.com", "facebook.com", "instagram.com", "x.com", "twitter.com"]
MISTRAL_AGENT_MODEL = os.getenv("MISTRAL_AGENT_MODEL", "mistral-medium-latest").strip()
MISTRAL_AGENT_NAME_PREFIX = os.getenv("MISTRAL_AGENT_NAME_PREFIX", "factcheck-live").strip() or "factcheck-live"
MISTRAL_RATE_LIMIT_MAX_RETRIES = int(os.getenv("MISTRAL_RATE_LIMIT_MAX_RETRIES", "4"))
MISTRAL_RATE_LIMIT_BACKOFF_BASE_SECONDS = float(
    os.getenv("MISTRAL_RATE_LIMIT_BACKOFF_BASE_SECONDS", "0.7")
)
MISTRAL_RATE_LIMIT_BACKOFF_MAX_SECONDS = float(
    os.getenv("MISTRAL_RATE_LIMIT_BACKOFF_MAX_SECONDS", "6.0")
)

# ── Per-agent model overrides ──────────────────────────────────────────────
# Each env var overrides the default_model set in AGENT_DEFINITIONS.
# If a var is unset, the agent-definition default is used (see agent_specs.py).
_AGENT_MODEL_KEYS = [
    "claim_extractor", "routeur", "statistique", "rhetorique",
    "coherence", "contexte", "editeur", "correction",
]
_AGENT_MODELS: dict[str, str] = {
    key: v
    for key in _AGENT_MODEL_KEYS
    if (v := os.getenv(f"MISTRAL_MODEL_{key.upper()}", "").strip())
}

RUNTIME_CONFIG = RuntimeConfig(
    agent_model=MISTRAL_AGENT_MODEL,
    agent_name_prefix=MISTRAL_AGENT_NAME_PREFIX,
    max_retries=MISTRAL_RATE_LIMIT_MAX_RETRIES,
    backoff_base_seconds=MISTRAL_RATE_LIMIT_BACKOFF_BASE_SECONDS,
    backoff_max_seconds=MISTRAL_RATE_LIMIT_BACKOFF_MAX_SECONDS,
    social_blacklist=SOCIAL_BLACKLIST,
    agent_models=_AGENT_MODELS,
)

# ── Persistent agent pool ──────────────────────────────────────────────────
# Created once at worker startup (init_agent_pool) and reused across all
# activity executions, saving ~12 Mistral API calls per sentence.
_ALL_AGENT_KEYS: list[str] = [
    "claim_extractor",
    "routeur", "statistique", "rhetorique", "coherence", "contexte", "editeur", "correction",
]
_POOL_INSTANCE: AgentPool | None = None


async def init_agent_pool() -> AgentPool:
    """Create the shared Mistral agent pool.  Called once at worker startup."""
    global _POOL_INSTANCE
    _POOL_INSTANCE = await create_agent_pool(
        client=client,
        config=RUNTIME_CONFIG,
        keys=_ALL_AGENT_KEYS,
    )
    print(f"✅ Agent pool ready ({len(_ALL_AGENT_KEYS)} agents)")
    return _POOL_INSTANCE


async def shutdown_agent_pool() -> None:
    """Delete all agents in the shared pool.  Called on worker shutdown."""
    global _POOL_INSTANCE
    if _POOL_INSTANCE is not None:
        await delete_agent_pool(client=client, pool=_POOL_INSTANCE)
        _POOL_INSTANCE = None
        print("🔴 Agent pool deleted")


def _extract_current_affirmation(current_json: dict) -> str:
    return extract_affirmation(current_json)


def _extract_previous_context_phrases(
    last_minute_json: dict, current_affirmation: str
) -> list[str]:
    previous_phrases = last_minute_json.get("previous_phrases")
    if isinstance(previous_phrases, list):
        return [
            phrase.strip()
            for phrase in previous_phrases
            if isinstance(phrase, str) and phrase.strip()
        ]

    # Backward compatibility with old payloads that only had `phrases`.
    phrases = [
        phrase.strip()
        for phrase in last_minute_json.get("phrases", [])
        if isinstance(phrase, str) and phrase.strip()
    ]
    if phrases and current_affirmation and phrases[-1] == current_affirmation:
        return phrases[:-1]
    return phrases


def _extract_numbers(text: str) -> list[str]:
    if not isinstance(text, str):
        return []
    return re.findall(r"\d+(?:[.,]\d+)?", text)


def _normalize_routing_decision(
    *,
    routage: dict[str, Any],
    affirmation_originale: str,
    question: str,
) -> dict[str, Any]:
    normalized: dict[str, Any] = dict(routage) if isinstance(routage, dict) else {}

    affirmation_propre = str(normalized.get("affirmation_propre", "")).strip()
    if not affirmation_propre:
        affirmation_propre = (affirmation_originale or "").strip()
    normalized["affirmation_propre"] = affirmation_propre

    for key in (
        "run_stats",
        "run_rhetorique",
        "run_coherence_personnelle",
        "run_contexte",
    ):
        normalized[key] = bool(normalized.get(key, False))

    if any(
        normalized[key]
        for key in (
            "run_stats",
            "run_rhetorique",
            "run_coherence_personnelle",
            "run_contexte",
        )
    ):
        return normalized

    # Fallback safety net: if router returns no actionable flag, avoid silently
    # skipping all checks. Keep deterministic, conservative defaults.
    has_numbers = bool(_extract_numbers(affirmation_propre))
    if has_numbers:
        normalized["run_stats"] = True
    else:
        normalized["run_contexte"] = True

    if isinstance(question, str) and question.strip().endswith("?"):
        normalized["run_rhetorique"] = True

    return normalized


def _heuristic_self_correction(
    current_affirmation: str, next_affirmation: str
) -> dict[str, Any]:
    normalized_next = (next_affirmation or "").strip().lower()
    if not normalized_next:
        return {
            "next_is_correction": False,
            "confidence": 0.0,
            "reason": "",
            "detector": "heuristic",
        }

    words = re.findall(r"[a-zA-ZÀ-ÿ0-9]+", normalized_next)
    has_marker = any(marker in normalized_next for marker in get_political_profile().correction_markers)
    current_numbers = _extract_numbers(current_affirmation)
    next_numbers = _extract_numbers(next_affirmation)
    replaces_number = bool(current_numbers and next_numbers and current_numbers != next_numbers)
    short_followup = len(words) <= 10

    if has_marker and (replaces_number or short_followup):
        return {
            "next_is_correction": True,
            "confidence": 0.95 if replaces_number else 0.85,
            "reason": "Correction explicite detectee (marqueur de correction).",
            "detector": "heuristic",
        }

    if replaces_number and short_followup:
        return {
            "next_is_correction": True,
            "confidence": 0.75,
            "reason": "Valeur numerique remplacee dans une phrase courte.",
            "detector": "heuristic",
        }

    return {
        "next_is_correction": False,
        "confidence": 0.2,
        "reason": "Pas de signal clair de correction explicite.",
        "detector": "heuristic",
    }


def _sanitize_primary_source(
    *,
    raw_result: dict[str, Any],
    sources: list[dict[str, str]],
) -> dict[str, Any]:
    sanitized = dict(raw_result)

    # Prefer inline sources written by the model into its JSON output ("sources" field).
    # These are the actual URLs the agent found during web_search — the most reliable path
    # since Mistral server-side tool.execution.info is always {}.
    inline_sources: list[dict[str, str]] = []
    raw_inline = raw_result.get("sources")
    if isinstance(raw_inline, list):
        for entry in raw_inline:
            if not isinstance(entry, dict):
                continue
            url = str(entry.get("url", "")).strip()
            if is_valid_http_url(url):
                inline_sources.append({
                    "organization": str(entry.get("organization", "")).strip()
                        or domain_to_organization(url),
                    "url": url,
                })

    # Fall back to sources extracted from conversation tool-call outputs.
    resolved_sources = inline_sources if inline_sources else sources

    if not resolved_sources:
        sanitized["source_is_relevant"] = False
        sanitized["nom_source"] = ""
        sanitized["url_source"] = ""
        sanitized["sources"] = []
        return sanitized

    preferred_source = resolved_sources[0]
    sanitized["source_is_relevant"] = True
    sanitized["nom_source"] = preferred_source.get("organization", "")
    sanitized["url_source"] = preferred_source.get("url", "")
    sanitized["sources"] = [
        {"organization": s.get("organization", ""), "url": s.get("url", "")}
        for s in resolved_sources
        if is_valid_http_url(s.get("url", ""))
    ]
    return sanitized


def _collect_sources_from_reports(rapports_agents: list[dict[str, Any]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    collected: list[dict[str, str]] = []
    for report in rapports_agents:
        if not isinstance(report, dict):
            continue
        raw_sources = report.get("sources")
        if isinstance(raw_sources, list):
            for source in raw_sources:
                if not isinstance(source, dict):
                    continue
                url = str(source.get("url", "")).strip()
                if not is_valid_http_url(url) or url in seen:
                    continue
                seen.add(url)
                collected.append(
                    {
                        "organization": str(source.get("organization", "")).strip()
                        or domain_to_organization(url),
                        "url": url,
                    }
                )
        single_url = str(report.get("url_source", "")).strip()
        if is_valid_http_url(single_url) and single_url not in seen:
            seen.add(single_url)
            collected.append(
                {
                    "organization": str(report.get("nom_source", "")).strip()
                    or domain_to_organization(single_url),
                    "url": single_url,
                }
            )
    return collected


def _first_source_for_agent(
    rapports_agents: list[dict[str, Any]], agent_name: str
) -> dict[str, str] | None:
    for report in rapports_agents:
        if not isinstance(report, dict):
            continue
        if str(report.get("agent", "")).strip() != agent_name:
            continue
        sources = report.get("sources")
        if isinstance(sources, list):
            for source in sources:
                if not isinstance(source, dict):
                    continue
                url = str(source.get("url", "")).strip()
                if not is_valid_http_url(url):
                    continue
                return {
                    "organization": str(source.get("organization", "")).strip()
                    or domain_to_organization(url),
                    "url": url,
                }
        url = str(report.get("url_source", "")).strip()
        if is_valid_http_url(url):
            return {
                "organization": str(report.get("nom_source", "")).strip()
                or domain_to_organization(url),
                "url": url,
            }
    return None


def _enrich_editor_result_with_sources(
    result: dict[str, Any], rapports_agents: list[dict[str, Any]]
) -> dict[str, Any]:
    enriched = copy.deepcopy(result)
    sources = _collect_sources_from_reports(rapports_agents)
    enriched["sources"] = sources

    explications = enriched.get("explications")
    if isinstance(explications, dict):
        mapping = {
            "statistique": "statistique",
            "contexte": "contexte",
            "coherence": "coherence",
        }
        for explication_key, agent_name in mapping.items():
            source = _first_source_for_agent(rapports_agents, agent_name)
            if not source:
                explication_value = explications.get(explication_key)
                if isinstance(explication_value, dict):
                    explication_value.pop("source", None)
                    explication_value.pop("url", None)
                continue
            explication_value = explications.get(explication_key)
            if isinstance(explication_value, dict):
                explication_value.setdefault("source", source["organization"])
                explication_value["url"] = source["url"]
            elif isinstance(explication_value, str) and explication_value.strip():
                explications[explication_key] = {
                    "texte": explication_value.strip(),
                    "source": source["organization"],
                    "url": source["url"],
                }
    return enriched


async def agent_statistique(data: dict[str, Any]) -> dict[str, Any]:
    print("📊 [Stats Agent] Deep verification running...")
    pool: AgentPool = data["__pool"]
    raw, selected_sources = await run_task(
        client=client,
        config=RUNTIME_CONFIG,
        pool=pool,
        specialist_key="statistique",
        specialist_prompt=build_stat_prompt(data),
    )
    if not selected_sources:
        return {
            "agent": "statistique",
            "verdict": "indetermine",
            "analyse_detaillee": (
                "Aucune source suffisamment pertinente avec lien n'a ete trouvee "
                "pour verifier cette affirmation."
            ),
            "source_is_relevant": False,
            "nom_source": "",
            "url_source": "",
            "sources": [],
        }
    return _sanitize_primary_source(raw_result=raw, sources=selected_sources)


async def agent_rhetorique(data: dict[str, Any]) -> dict[str, Any]:
    print("🧠 [Rhetoric Agent] Logical analysis...")
    pool: AgentPool = data["__pool"]
    raw, _ = await run_task(
        client=client,
        config=RUNTIME_CONFIG,
        pool=pool,
        specialist_key="rhetorique",
        specialist_prompt=build_rhetorique_prompt(data),
    )
    return raw


async def agent_coherence_personnelle(data: dict[str, Any]) -> dict[str, Any]:
    print(f"🕵️ [Consistency Agent] Checking public statements for {data['personne']}...")
    pool: AgentPool = data["__pool"]
    raw, selected_sources = await run_task(
        client=client,
        config=RUNTIME_CONFIG,
        pool=pool,
        specialist_key="coherence",
        specialist_prompt=build_coherence_prompt(data),
    )
    if not selected_sources:
        return {
            "agent": "coherence",
            "explication": "",
            "source_is_relevant": False,
            "nom_source": "",
            "url_source": "",
            "sources": [],
        }
    return _sanitize_primary_source(raw_result=raw, sources=selected_sources)


async def agent_contexte(data: dict[str, Any]) -> dict[str, Any]:
    print("📚 [Context Agent] Detailed factual context analysis...")
    pool: AgentPool = data["__pool"]
    raw, selected_sources = await run_task(
        client=client,
        config=RUNTIME_CONFIG,
        pool=pool,
        specialist_key="contexte",
        specialist_prompt=build_contexte_prompt(data),
    )
    if not selected_sources:
        return {
            "agent": "contexte",
            "analyse_detaillee": (
                "Aucune source suffisamment pertinente avec lien n'a ete trouvee "
                "pour contextualiser cette affirmation."
            ),
            "source_is_relevant": False,
            "nom_source": "",
            "url_source": "",
            "sources": [],
        }
    return _sanitize_primary_source(raw_result=raw, sources=selected_sources)


async def agent_routeur(data: dict[str, Any]) -> dict[str, Any]:
    pool: AgentPool = data["__pool"]
    raw, _ = await run_task(
        client=client,
        config=RUNTIME_CONFIG,
        pool=pool,
        specialist_key="routeur",
        specialist_prompt=build_routeur_prompt(data),
    )
    return raw


async def executer_analyse_parallele(data: dict[str, Any], *, pool: AgentPool) -> list[dict[str, Any]]:
    print(f"🚦 CURRENT SENTENCE: '{data['affirmation'][:60]}...'")

    data_with_pool = dict(data)
    data_with_pool["__pool"] = pool
    routage_brut = await agent_routeur(data_with_pool)
    routage = _normalize_routing_decision(
        routage=routage_brut,
        affirmation_originale=data["affirmation"],
        question=data.get("question_posee", ""),
    )
    affirmation_propre = routage.get("affirmation_propre", data["affirmation"])
    print(f"✨ CLEAN TEXT: '{affirmation_propre}'")

    data_propre = dict(data)
    data_propre["affirmation"] = affirmation_propre
    data_propre["__pool"] = pool

    tasks = []
    if routage.get("run_stats"):
        tasks.append(agent_statistique(data_propre))
    if routage.get("run_rhetorique"):
        tasks.append(agent_rhetorique(data_propre))
    if routage.get("run_coherence_personnelle"):
        tasks.append(agent_coherence_personnelle(data_propre))
    if routage.get("run_contexte"):
        tasks.append(agent_contexte(data_propre))

    if not tasks:
        return []

    print(f"🚀 RUNNING: {len(tasks)} agent(s) on cleaned sentence...")
    return await asyncio.gather(*tasks)


async def agent_editeur(
    contexte_precedent: str,
    affirmation_actuelle: str,
    rapports_agents: list[dict[str, Any]],
    *,
    pool: AgentPool,
) -> dict[str, Any]:
    print("📝 [Editor Agent] Final newsroom synthesis...")

    if not rapports_agents:
        return {"raison": "Aucun fact-check nécessaire."}

    raw, _ = await run_task(
        client=client,
        config=RUNTIME_CONFIG,
        pool=pool,
        specialist_key="editeur",
        specialist_prompt=build_editor_prompt(
            contexte_precedent=contexte_precedent,
            affirmation_actuelle=affirmation_actuelle,
            rapports_agents=rapports_agents,
        ),
    )
    return raw


@activity.defn
async def analyze_debate_line(current_json: dict, last_minute_json: dict) -> dict:
    """
    Main activity called by Temporal for each detected sentence.
    """
    personne = current_json.get("personne", "Intervenant inconnu")
    question = current_json.get("question_posee", "")
    affirmation = _extract_current_affirmation(current_json)
    if not affirmation:
        return {"raison": "Phrase courante vide."}

    # Context never includes current phrase to avoid self-repetition.
    phrases_contexte = _extract_previous_context_phrases(last_minute_json, affirmation)
    contexte_precedent = " ".join(phrases_contexte)

    data_pour_agents = {
        "personne": personne,
        "question_posee": question,
        "affirmation": affirmation,
        "contexte_precedent": contexte_precedent,
    }

    print(
        f"🎤 Analysis in progress for {personne} "
        f"(current_sentence='{affirmation[:80]}', context_phrases={len(phrases_contexte)})..."
    )

    pool = _POOL_INSTANCE
    if pool is None:
        raise ApplicationError(
            "Agent pool not initialized. Call init_agent_pool() before starting the worker.",
            non_retryable=True,
        )

    rapports_bruts = await executer_analyse_parallele(data_pour_agents, pool=pool)

    resultat_final = await agent_editeur(
        contexte_precedent=contexte_precedent,
        affirmation_actuelle=affirmation,
        rapports_agents=rapports_bruts,
        pool=pool,
    )

    if not isinstance(resultat_final, dict):
        return {"raison": "Resultat editeur invalide."}

    resultat_final = _enrich_editor_result_with_sources(resultat_final, rapports_bruts)

    # Carry the original claim text and speaker through so posting activities
    # can populate the structured fact schema without re-parsing the raw result.
    resultat_final.setdefault("affirmation", affirmation)
    resultat_final.setdefault("personne", personne)

    if not resultat_final.get("sources"):
        resultat_final.setdefault(
            "source_warning",
            "Aucune source URL fiable n'a pu etre extraite automatiquement.",
        )
        explications = resultat_final.get("explications")
        if isinstance(explications, dict):
            for value in explications.values():
                if isinstance(value, dict):
                    value.pop("source", None)
                    value.pop("url", None)

    return resultat_final


@activity.defn
async def check_next_phrase_self_correction(
    current_json: dict,
    next_json: dict | None,
    last_minute_json: dict,
) -> dict:
    """
    Detects whether the next sentence corrects/cancels the current one.
    """
    current_affirmation = _extract_current_affirmation(current_json)
    next_affirmation = _extract_current_affirmation(next_json or {})

    if not current_affirmation:
        return {
            "has_next_phrase": bool(next_affirmation),
            "next_is_correction": False,
            "confidence": 0.0,
            "reason": "Phrase courante vide.",
        }

    if not next_affirmation:
        return {
            "has_next_phrase": False,
            "next_is_correction": False,
            "confidence": 0.0,
            "reason": "Aucune phrase suivante complete.",
        }

    heuristic = _heuristic_self_correction(current_affirmation, next_affirmation)
    if bool(heuristic.get("next_is_correction")):
        return {
            "has_next_phrase": True,
            "next_is_correction": True,
            "confidence": float(heuristic.get("confidence", 0.0)),
            "reason": str(heuristic.get("reason", "")),
            "detector": "heuristic",
            "current_affirmation": current_affirmation,
            "next_affirmation": next_affirmation,
        }

    contexte_precedent = " ".join(
        _extract_previous_context_phrases(last_minute_json, current_affirmation)
    )

    pool = _POOL_INSTANCE
    if pool is None or "correction" not in pool.specialist_ids:
        return {
            "has_next_phrase": True,
            "next_is_correction": bool(heuristic.get("next_is_correction", False)),
            "confidence": float(heuristic.get("confidence", 0.0)),
            "reason": (
                "Agent pool indisponible, fallback heuristique: "
                f"{heuristic.get('reason', 'indetermine')}"
            ),
            "detector": "heuristic_fallback_no_pool",
            "current_affirmation": current_affirmation,
            "next_affirmation": next_affirmation,
        }

    try:
        parsed, _ = await run_task(
            client=client,
            config=RUNTIME_CONFIG,
            pool=pool,
            specialist_key="correction",
            specialist_prompt=build_self_correction_prompt(
                current_affirmation=current_affirmation,
                next_affirmation=next_affirmation,
                contexte_precedent=contexte_precedent,
            ),
        )

        next_is_correction = bool(parsed.get("next_is_correction", False))
        try:
            confidence = float(parsed.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        reason = str(parsed.get("reason", "")).strip()

        return {
            "has_next_phrase": True,
            "next_is_correction": next_is_correction,
            "confidence": confidence,
            "reason": reason,
            "detector": "llm",
            "current_affirmation": current_affirmation,
            "next_affirmation": next_affirmation,
        }
    except Exception as exc:
        return {
            "has_next_phrase": True,
            "next_is_correction": bool(heuristic.get("next_is_correction", False)),
            "confidence": float(heuristic.get("confidence", 0.0)),
            "reason": (
                "LLM indisponible, fallback heuristique: "
                f"{heuristic.get('reason', 'indetermine')}"
            ),
            "detector": "heuristic_fallback_after_llm_error",
            "error": str(exc),
            "current_affirmation": current_affirmation,
            "next_affirmation": next_affirmation,
        }


@activity.defn
async def post_fact_check_result(payload: dict) -> dict:
    """
    Sends workflow result to stream fact-check service.

    Raises ``ApplicationError`` on failure so that Temporal's ``_POST_RETRY``
    policy actually fires.  4xx responses are marked ``non_retryable=True``
    (client errors — retrying won’t help).
    """
    url = os.getenv("FACT_CHECK_POST_URL", DEFAULT_FACT_CHECK_POST_URL)

    def _do_post():
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return resp

    try:
        response = await asyncio.to_thread(_do_post)
        body_preview = response.text[:1000]
        return {
            "posted": True,
            "status_code": response.status_code,
            "url": url,
            "response_body_preview": body_preview,
        }
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 0
        if 400 <= status < 500:
            raise ApplicationError(
                f"HTTP {status} from {url} — non-retryable client error",
                non_retryable=True,
            ) from exc
        raise ApplicationError(f"HTTP {status} server error from {url}") from exc
    except requests.Timeout as exc:
        raise ApplicationError(f"Request timed out posting to {url}") from exc
    except requests.ConnectionError as exc:
        raise ApplicationError(f"Connection error posting to {url}") from exc
    except Exception as exc:
        raise ApplicationError(f"Unexpected error posting to {url}: {exc}") from exc


@activity.defn
async def post_fact_check_to_veristral(payload: dict) -> dict:
    """
    Sends the fact-check verdict to the facts app ``POST /api/facts`` endpoint.

    Transforms the raw analysis result into the ``StoreFactRequest`` schema::

        {
            "broadcast_uuid": str,
            "claim":    { "text": str },
            "analysis": { "summary": str, "sources": [{"url": str, "organization": str}] },
            "overall_verdict": str,
        }

    Raises ``ApplicationError`` on failure so Temporal's retry policy fires.
    4xx errors are marked non-retryable.
    """
    url = os.getenv("VERISTRAL_POST_URL", DEFAULT_VERISTRAL_POST_URL)
    broadcast_uuid = os.getenv("BROADCAST_UUID", "").strip()

    # ── Build the structured payload expected by StoreFactRequest ─────────────
    verdict = payload.get("verdict_global") or payload.get("overall_verdict") or "indetermine"
    claim_text = payload.get("affirmation") or payload.get("claim", {}).get("text") or ""
    summary = (
        payload.get("raison")
        or payload.get("analysis", {}).get("summary")
        or verdict
    )
    raw_sources = payload.get("sources") or payload.get("analysis", {}).get("sources") or []
    sources = [
        {"url": s.get("url", ""), "organization": s.get("organization", "")}
        for s in raw_sources
        if isinstance(s, dict) and s.get("url") and s.get("organization")
    ]

    facts_payload: dict = {
        "broadcast_uuid": broadcast_uuid,
        "claim": {"text": claim_text},
        "analysis": {"summary": summary, "sources": sources},
        "overall_verdict": verdict,
    }

    def _do_post():
        resp = requests.post(url, json=facts_payload, timeout=10)
        resp.raise_for_status()
        return resp

    try:
        response = await asyncio.to_thread(_do_post)
        body_preview = response.text[:1000]
        return {
            "posted": True,
            "status_code": response.status_code,
            "url": url,
            "response_body_preview": body_preview,
        }
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 0
        if 400 <= status < 500:
            raise ApplicationError(
                f"HTTP {status} from {url} — non-retryable client error",
                non_retryable=True,
            ) from exc
        raise ApplicationError(f"HTTP {status} server error from {url}") from exc
    except requests.Timeout as exc:
        raise ApplicationError(f"Request timed out posting to {url}") from exc
    except requests.ConnectionError as exc:
        raise ApplicationError(f"Connection error posting to {url}") from exc
    except Exception as exc:
        raise ApplicationError(f"Unexpected error posting to {url}: {exc}") from exc


@activity.defn
async def extract_claims_from_transcript(batch: dict) -> dict:
    """Extract verifiable factual claims from a STT transcript window.

    *batch* must contain:
    - ``sentences``    — list of STT sentence dicts (each with ``text``, ``personne``,
      ``question_posee``, and optionally ``timestamp``)
    - ``personne``     — speaker name (fallback if individual sentences lack it)
    - ``question_posee`` — journalist's question (fallback)

    Returns a plain dict with a ``claims`` list, where each entry is an
    ``ExtractedClaim``-shaped dict (``affirmation``, ``contexte``, ``personne``,
    ``question_posee``, ``type_claim``).

    The model is intentionally fast (``claim_extractor`` uses ``_FAST_MODEL``) because
    this step runs on every ~20-second window and latency matters more than raw accuracy.
    The downstream fact-check workflow handles deeper analysis.
    """
    pool = _POOL_INSTANCE
    if pool is None:
        raise ApplicationError("Agent pool not initialised — call init_agent_pool() first.")

    sentences_raw: list[dict] = batch.get("sentences", [])
    personne: str = str(batch.get("personne", "")).strip()
    question_posee: str = str(batch.get("question_posee", "")).strip()

    # Build a flat list of sentence texts, using per-sentence speaker if available.
    sentence_texts: list[str] = []
    for s in sentences_raw:
        if not isinstance(s, dict):
            continue
        text = str(s.get("text", s.get("affirmation_courante", s.get("affirmation", "")))).strip()
        if text:
            sentence_texts.append(text)

    if not sentence_texts:
        return {"claims": [], "skipped": True, "reason": "empty transcript window"}

    prompt = build_claim_extraction_prompt(
        sentences=sentence_texts,
        personne=personne,
        question_posee=question_posee,
    )

    print(
        f"🔍 [ClaimExtractor] analysing {len(sentence_texts)} sentences "
        f"(speaker={personne!r}, question={question_posee[:60]!r}…)"
    )

    raw, _ = await run_task(
        client=client,
        config=RUNTIME_CONFIG,
        pool=pool,
        specialist_key="claim_extractor",
        specialist_prompt=prompt,
    )

    claims_raw = raw.get("claims", [])
    if not isinstance(claims_raw, list):
        claims_raw = []

    # Validate and normalise each claim.
    valid_claims: list[dict] = []
    for item in claims_raw:
        if not isinstance(item, dict):
            continue
        affirmation = str(item.get("affirmation", "")).strip()
        if not affirmation:
            continue
        valid_claims.append({
            "affirmation": affirmation,
            "contexte": str(item.get("contexte", "")).strip(),
            "personne": str(item.get("personne", personne)).strip() or personne,
            "question_posee": str(item.get("question_posee", question_posee)).strip() or question_posee,
            "type_claim": str(item.get("type_claim", "autre")).strip() or "autre",
        })

    print(
        f"✅ [ClaimExtractor] {len(valid_claims)} checkworthy claim(s) extracted "
        f"(from {len(sentence_texts)} sentences)"
    )
    for i, c in enumerate(valid_claims, 1):
        print(f"  [{i}] [{c['type_claim']}] {c['affirmation'][:120]}")

    return {"claims": valid_claims}


async def _demo_main() -> None:
    """Local smoke demo with fake data for quick manual testing."""
    fake_current = {
        "personne": "Demo Speaker",
        "question_posee": "How many jobs were created last year?",
        "affirmation": "We created 1.2 million jobs last year.",
    }
    fake_next = {
        "personne": "Demo Speaker",
        "question_posee": "How many jobs were created last year?",
        "affirmation": "Sorry, I correct myself: it was 1.1 million.",
    }
    fake_last_minute = {
        "previous_phrases": [
            "Our economy is recovering.",
            "Unemployment has decreased.",
            "Public spending stayed stable.",
        ]
    }

    print("\n=== DEMO INPUTS ===")
    print(json.dumps({
        "current_json": fake_current,
        "next_json": fake_next,
        "last_minute_json": fake_last_minute,
    }, ensure_ascii=False, indent=2))

    if not os.getenv("MISTRAL_API_KEY"):
        print("\n⚠️ MISTRAL_API_KEY is missing. Demo stops before remote calls.")
        return

    print("\n=== RUN: analyze_debate_line ===")
    analysis = await analyze_debate_line(fake_current, fake_last_minute)
    print(json.dumps(analysis, ensure_ascii=False, indent=2))

    print("\n=== RUN: check_next_phrase_self_correction ===")
    correction = await check_next_phrase_self_correction(fake_current, fake_next, fake_last_minute)
    print(json.dumps(correction, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_demo_main())
