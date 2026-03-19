import os
import json
import asyncio 
import re
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import requests
from temporalio import activity
from mistralai import Mistral
from dotenv import load_dotenv
from transcript_archive import archive_transcript_entry_payload

# --- ASTUCE POUR LE CHEMIN DES CLÉS ---
# On récupère le chemin du dossier 'workflows'
current_dir = Path(__file__).parent
# On remonte d'un cran pour atteindre la racine où se trouve 'cle.env'
env_path = current_dir.parent / "cle.env"

# On charge le fichier spécifiquement
load_dotenv(dotenv_path=env_path)

# Vérification (optionnelle pour débugger)
if not os.getenv("MISTRAL_API_KEY"):
    print(f"❌ Erreur : Impossible de trouver les clés dans {env_path}")
else:
    print(f"✅ Clés chargées depuis {env_path}")

# Initialisation des clients
client = Mistral(api_key=os.getenv("MISTRAL_API_KEY"))

SOCIAL_BLACKLIST = ["tiktok.com", "facebook.com", "instagram.com", "x.com", "twitter.com"]
DEFAULT_FACT_CHECK_POST_URL = "http://localhost:8000/api/stream/fact-check"
MISTRAL_WEB_SEARCH_MODEL = os.getenv(
    "MISTRAL_WEB_SEARCH_MODEL", "mistral-medium-latest"
).strip()
SOURCE_SELECTION_MODE = os.getenv("SOURCE_SELECTION_MODE", "heuristic").strip().lower()
MISTRAL_RATE_LIMIT_MAX_RETRIES = int(
    os.getenv("MISTRAL_RATE_LIMIT_MAX_RETRIES", "4")
)
MISTRAL_RATE_LIMIT_BACKOFF_BASE_SECONDS = float(
    os.getenv("MISTRAL_RATE_LIMIT_BACKOFF_BASE_SECONDS", "0.7")
)
MISTRAL_RATE_LIMIT_BACKOFF_MAX_SECONDS = float(
    os.getenv("MISTRAL_RATE_LIMIT_BACKOFF_MAX_SECONDS", "6.0")
)
CORRECTION_MARKERS = [
    "pardon",
    "je corrige",
    "je me corrige",
    "je me suis trompe",
    "je me suis trompé",
    "plutot",
    "plutôt",
    "rectification",
    "en fait",
    "non",
]
FRENCH_STOPWORDS = {
    "alors",
    "avec",
    "avoir",
    "bien",
    "cette",
    "dans",
    "dont",
    "elle",
    "elles",
    "entre",
    "etre",
    "fait",
    "faire",
    "mais",
    "meme",
    "nous",
    "pour",
    "plus",
    "pas",
    "que",
    "qui",
    "sans",
    "sont",
    "sur",
    "tout",
    "tous",
    "tres",
    "une",
    "des",
    "les",
    "du",
    "de",
    "la",
    "le",
    "un",
    "est",
    "et",
    "ou",
    "en",
    "il",
    "ils",
    "elle",
    "on",
    "je",
    "tu",
    "vous",
    "nous",
}


def _is_rate_limited_error(exc: Exception) -> bool:
    lowered = str(exc).lower()
    return (
        "rate limit" in lowered
        or "status 429" in lowered
        or "\"code\":\"1300\"" in lowered
        or "'code':'1300'" in lowered
    )


async def _mistral_json(
    prompt: str, *, model: str = "mistral-small-latest"
) -> dict[str, Any]:
    max_retries = max(0, MISTRAL_RATE_LIMIT_MAX_RETRIES)
    for attempt in range(max_retries + 1):
        try:
            res = await client.chat.complete_async(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
            parsed = json.loads(res.choices[0].message.content)
            if isinstance(parsed, dict):
                return parsed
            return {"value": parsed}
        except Exception as exc:
            should_retry = _is_rate_limited_error(exc) and attempt < max_retries
            if not should_retry:
                raise
            backoff = min(
                MISTRAL_RATE_LIMIT_BACKOFF_MAX_SECONDS,
                MISTRAL_RATE_LIMIT_BACKOFF_BASE_SECONDS * (2 ** attempt),
            )
            jitter = random.uniform(0.0, 0.25 * max(0.2, backoff))
            wait_seconds = backoff + jitter
            print(
                "[mistral] rate limit detecte, retry "
                f"{attempt + 1}/{max_retries} dans {wait_seconds:.2f}s"
            )
            await asyncio.sleep(wait_seconds)


def _extract_current_affirmation(current_json: dict) -> str:
    current = current_json.get("affirmation_courante")
    if isinstance(current, str) and current.strip():
        return current.strip()
    fallback = current_json.get("affirmation")
    if isinstance(fallback, str) and fallback.strip():
        return fallback.strip()
    return ""


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


def _is_valid_http_url(url: str) -> bool:
    if not isinstance(url, str):
        return False
    stripped = url.strip().lower()
    return stripped.startswith("http://") or stripped.startswith("https://")


def _domain_to_organization(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        host = ""
    if host.startswith("www."):
        host = host[4:]
    return host or "source-inconnue"


def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-zA-ZÀ-ÿ0-9]+", (text or "").lower())
    return [
        token
        for token in tokens
        if len(token) >= 3 and token not in FRENCH_STOPWORDS
    ]


def _extract_numbers(text: str) -> list[str]:
    if not isinstance(text, str):
        return []
    return re.findall(r"\d+(?:[.,]\d+)?", text)


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
    has_marker = any(marker in normalized_next for marker in CORRECTION_MARKERS)
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


def _fallback_select_relevant_sources(
    *,
    assertion: str,
    question: str,
    candidates: list[dict[str, Any]],
) -> list[int]:
    needed_tokens = set(_tokenize(f"{assertion} {question}"))
    if not candidates:
        return []
    if not needed_tokens:
        return [int(candidates[0]["id"])]

    scored: list[tuple[float, int]] = []
    for candidate in candidates:
        haystack = " ".join(
            [
                str(candidate.get("title", "")),
                str(candidate.get("snippet", "")),
                str(candidate.get("url", "")),
            ]
        )
        candidate_tokens = set(_tokenize(haystack))
        overlap = len(needed_tokens.intersection(candidate_tokens))
        if overlap > 0:
            score = overlap / max(1, len(needed_tokens))
            scored.append((score, int(candidate["id"])))
    scored.sort(reverse=True)
    return [source_id for _, source_id in scored[:3]]


async def _mistral_web_search_response(query: str) -> Any:
    max_retries = max(0, MISTRAL_RATE_LIMIT_MAX_RETRIES)
    for attempt in range(max_retries + 1):
        try:
            return await client.beta.conversations.start_async(
                model=MISTRAL_WEB_SEARCH_MODEL,
                inputs=query,
                tools=[{"type": "web_search"}],
                completion_args={"temperature": 0.0},
            )
        except Exception as exc:
            should_retry = _is_rate_limited_error(exc) and attempt < max_retries
            if not should_retry:
                raise
            backoff = min(
                MISTRAL_RATE_LIMIT_BACKOFF_MAX_SECONDS,
                MISTRAL_RATE_LIMIT_BACKOFF_BASE_SECONDS * (2 ** attempt),
            )
            jitter = random.uniform(0.0, 0.25 * max(0.2, backoff))
            wait_seconds = backoff + jitter
            print(
                "[mistral-web-search] rate limit detecte, retry "
                f"{attempt + 1}/{max_retries} dans {wait_seconds:.2f}s"
            )
            await asyncio.sleep(wait_seconds)


def _collect_candidates_from_any(
    value: Any, collected: list[dict[str, str]]
) -> None:
    if isinstance(value, dict):
        raw_url = value.get("url")
        if isinstance(raw_url, str) and _is_valid_http_url(raw_url):
            title = str(value.get("title", "")).strip()
            snippet = str(
                value.get("description", "")
                or value.get("snippet", "")
                or value.get("content", "")
            ).strip()
            collected.append(
                {
                    "url": raw_url.strip(),
                    "title": title,
                    "snippet": snippet[:480],
                }
            )
        for inner in value.values():
            _collect_candidates_from_any(inner, collected)
        return

    if isinstance(value, list):
        for item in value:
            _collect_candidates_from_any(item, collected)


def _extract_mistral_web_candidates(response: Any) -> list[dict[str, str]]:
    payload = response.model_dump() if hasattr(response, "model_dump") else response
    if not isinstance(payload, dict):
        return []
    outputs = payload.get("outputs", [])
    if not isinstance(outputs, list):
        return []

    candidates: list[dict[str, str]] = []
    for output in outputs:
        if not isinstance(output, dict):
            continue
        output_type = str(output.get("type", ""))
        if output_type == "message.output":
            content = output.get("content")
            _collect_candidates_from_any(content, candidates)
        elif output_type == "tool.execution":
            _collect_candidates_from_any(output.get("info"), candidates)
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for candidate in candidates:
        url = str(candidate.get("url", "")).strip()
        if not _is_valid_http_url(url) or url in seen:
            continue
        try:
            host = urlparse(url).netloc.lower()
        except Exception:
            host = ""
        if host.startswith("www."):
            host = host[4:]
        if any(host == blocked or host.endswith(f".{blocked}") for blocked in SOCIAL_BLACKLIST):
            continue
        seen.add(url)
        deduped.append(
            {
                "url": url,
                "title": str(candidate.get("title", "")).strip(),
                "snippet": str(candidate.get("snippet", "")).strip()[:480],
            }
        )
    return deduped


async def _search_relevant_sources(
    *,
    assertion: str,
    question: str,
    query: str,
    search_depth: str = "basic",
    max_results: int = 6,
    exclude_domains: list[str] | None = None,
) -> list[dict[str, str]]:
    del search_depth  # Conservé pour compatibilité d'interface.
    excluded = set(exclude_domains or [])
    excluded.update(SOCIAL_BLACKLIST)
    web_query = (
        f"{query}\n\n"
        f"Affirmation: {assertion}\n"
        f"Question: {question}\n"
        "Trouve des pages pertinentes qui répondent directement à la vérification."
    )
    try:
        response = await _mistral_web_search_response(web_query)
        raw_candidates = _extract_mistral_web_candidates(response)
    except Exception as exc:
        print(f"❌ Erreur Mistral Web Search: {exc}")
        raw_candidates = []

    filtered_candidates: list[dict[str, str]] = []
    for item in raw_candidates:
        url = str(item.get("url", "")).strip()
        if not _is_valid_http_url(url):
            continue
        try:
            host = urlparse(url).netloc.lower()
        except Exception:
            host = ""
        if host.startswith("www."):
            host = host[4:]
        if any(host == blocked or host.endswith(f".{blocked}") for blocked in excluded):
            continue
        filtered_candidates.append(item)
        if len(filtered_candidates) >= max_results:
            break

    candidates: list[dict[str, Any]] = []
    for idx, item in enumerate(filtered_candidates, start=1):
        candidates.append(
            {
                "id": idx,
                "url": item["url"],
                "title": str(item.get("title", "")).strip(),
                "snippet": str(item.get("snippet", "")).strip()[:480],
            }
        )

    if not candidates:
        return []

    selection_prompt = f"""Tu sélectionnes des sources fact-check.

Affirmation à vérifier:
"{assertion}"

Question posée:
"{question}"

Sources candidates:
{json.dumps(candidates, ensure_ascii=False)}

Règles:
1. Garde uniquement les sources qui répondent directement à l'affirmation/question.
2. Rejette les sources hors-sujet (ex: mauvaise ville/pays/contexte).
3. Si aucune source n'est pertinente, renvoie une liste vide.

JSON strict:
{{
  "selected_ids": [1,2,3]
}}
"""
    selected_ids: list[int] = []
    if SOURCE_SELECTION_MODE == "llm":
        try:
            parsed = await _mistral_json(selection_prompt)
            raw_ids = parsed.get("selected_ids", [])
            if isinstance(raw_ids, list):
                for raw_id in raw_ids:
                    try:
                        source_id = int(raw_id)
                    except (TypeError, ValueError):
                        continue
                    if any(c["id"] == source_id for c in candidates):
                        selected_ids.append(source_id)
        except Exception as exc:
            print(f"⚠️ Sélection LLM des sources échouée: {exc}")

    if not selected_ids:
        selected_ids = _fallback_select_relevant_sources(
            assertion=assertion,
            question=question,
            candidates=candidates,
        )

    selected_ids = list(dict.fromkeys(selected_ids))[:3]
    selected = [c for c in candidates if int(c["id"]) in selected_ids]
    return [
        {
            "organization": _domain_to_organization(item["url"]),
            "url": item["url"],
            "title": item["title"],
            "snippet": item["snippet"],
        }
        for item in selected
    ]


def _sources_for_prompt(sources: list[dict[str, str]]) -> str:
    if not sources:
        return "Aucune source."
    lines: list[str] = []
    for idx, source in enumerate(sources, start=1):
        lines.append(
            f"[{idx}] org={source.get('organization', '')} "
            f"url={source.get('url', '')} "
            f"title={source.get('title', '')} "
            f"snippet={source.get('snippet', '')}"
        )
    return "\n".join(lines)


def _sanitize_primary_source(
    *,
    raw_result: dict[str, Any],
    sources: list[dict[str, str]],
) -> dict[str, Any]:
    sanitized = dict(raw_result)
    if not sources:
        sanitized["source_is_relevant"] = False
        sanitized["nom_source"] = ""
        sanitized["url_source"] = ""
        sanitized["sources"] = []
        return sanitized

    preferred_source = sources[0]
    try:
        selected_index = int(raw_result.get("source_index", 1))
    except (TypeError, ValueError):
        selected_index = 1
    if 1 <= selected_index <= len(sources):
        preferred_source = sources[selected_index - 1]

    sanitized["source_is_relevant"] = True
    sanitized["nom_source"] = preferred_source.get("organization", "")
    sanitized["url_source"] = preferred_source.get("url", "")
    sanitized["sources"] = [
        {"organization": s.get("organization", ""), "url": s.get("url", "")}
        for s in sources
        if _is_valid_http_url(s.get("url", ""))
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
                if not _is_valid_http_url(url) or url in seen:
                    continue
                seen.add(url)
                collected.append(
                    {
                        "organization": str(source.get("organization", "")).strip()
                        or _domain_to_organization(url),
                        "url": url,
                    }
                )
        single_url = str(report.get("url_source", "")).strip()
        if _is_valid_http_url(single_url) and single_url not in seen:
            seen.add(single_url)
            collected.append(
                {
                    "organization": str(report.get("nom_source", "")).strip()
                    or _domain_to_organization(single_url),
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
                if not _is_valid_http_url(url):
                    continue
                return {
                    "organization": str(source.get("organization", "")).strip()
                    or _domain_to_organization(url),
                    "url": url,
                }
        url = str(report.get("url_source", "")).strip()
        if _is_valid_http_url(url):
            return {
                "organization": str(report.get("nom_source", "")).strip()
                or _domain_to_organization(url),
                "url": url,
            }
    return None


def _enrich_editor_result_with_sources(
    result: dict[str, Any], rapports_agents: list[dict[str, Any]]
) -> dict[str, Any]:
    enriched = dict(result)
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

# --- AGENT 1 : STATISTIQUES (MODE INVESTIGATION LIBRE) ---
async def agent_statistique(data):
    print(f"📊 [Agent Stat] Investigation approfondie en cours...")
    
    query_complete = (
        f"{data['affirmation']} {data.get('question_posee', '')} "
        "(site:gouv.fr OR site:insee.fr OR site:vie-publique.fr OR site:afp.com "
        "OR site:lemonde.fr OR site:lefigaro.fr)"
    )
    selected_sources = await _search_relevant_sources(
        assertion=data.get("affirmation", ""),
        question=data.get("question_posee", ""),
        query=query_complete,
        search_depth="basic",
        max_results=8,
        exclude_domains=SOCIAL_BLACKLIST,
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

    prompt = f"""Vérifie cette affirmation : '{data['affirmation']}'.
    Question posée : '{data.get('question_posee', '')}'.
    Sources validées pertinentes (utilise UNIQUEMENT celles-ci) :
    {_sources_for_prompt(selected_sources)}

    RÈGLES STRICTES :
    1. verdict : "vrai", "faux", "exagéré", "trompeur" (sois précis sur la nuance).
    2. analyse_detaillee : Fais une analyse détaillée (environ 5 à 7 phrases). Décortique le chiffre, donne le vrai chiffre, ajoute de la nuance si la méthode de calcul du politicien est biaisée.
    3. source_index : index numérique de la source principale (1..N).
    
    JSON: {{"agent": "statistique", "verdict": "vrai|faux|...", "analyse_detaillee": "...", "source_index": 1}}"""
    
    raw = await _mistral_json(prompt)
    return _sanitize_primary_source(raw_result=raw, sources=selected_sources)

# --- AGENT 2 : RHÉTORIQUE ---
async def agent_rhetorique(data):
    print(f"🧠 [Agent Rhétorique] Analyse logique...")
    prompt = f"""Analyse : Question posée : '{data.get('question_posee', '')}' | Réponse : '{data.get('affirmation', '')}'
    RÈGLES STRICTES :
    1. Si la personne répond à la question (ou s'il n'y avait pas de question) : Laisse "explication" VIDE "".
    2. Si la personne esquive : Explique en une phrase qu'elle ne répond pas à la question posée.
    
    JSON: {{"agent": "rhetorique", "explication": "..."}}"""
    
    return await _mistral_json(prompt)

# --- AGENT 3 : COHÉRENCE PERSONNELLE ---
async def agent_coherence_personnelle(data):
    print(f"🕵️ [Agent Cohérence] Accès réseaux sociaux pour {data['personne']}...")
    query = (
        f"déclaration {data['personne']} {data['affirmation']} "
        f"{data.get('question_posee', '')} 2024 2025 2026"
    )
    selected_sources = await _search_relevant_sources(
        assertion=data.get("affirmation", ""),
        question=data.get("question_posee", ""),
        query=query,
        search_depth="advanced",
        max_results=8,
        exclude_domains=SOCIAL_BLACKLIST,
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

    prompt = f"""Vérifie si {data['personne']} se contredit sur : '{data['affirmation']}'.
    Sources validées pertinentes (utilise UNIQUEMENT celles-ci) :
    {_sources_for_prompt(selected_sources)}

    RÈGLES STRICTES :
    1. Si la personne est cohérente : Laisse "explication" VIDE "".
    2. Si incohérente : Cite brièvement les propos incohérents.
    3. source_index : index numérique de la source principale (1..N).
    
    JSON: {{"agent": "coherence", "explication": "...", "source_index": 1}}"""
    
    raw = await _mistral_json(prompt)
    return _sanitize_primary_source(raw_result=raw, sources=selected_sources)

# --- AGENT 4 : CONTEXTE (MODE INVESTIGATION LIBRE) ---
async def agent_contexte(data):
    print(f"📚 [Agent Contexte] Analyse factuelle détaillée...")
    
    query_complete = (
        f"{data['affirmation']} {data.get('question_posee', '')} "
        "contexte faits historiques France 2024 2025 2026"
    )
    selected_sources = await _search_relevant_sources(
        assertion=data.get("affirmation", ""),
        question=data.get("question_posee", ""),
        query=query_complete,
        search_depth="basic",
        max_results=8,
        exclude_domains=SOCIAL_BLACKLIST,
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

    prompt = f"""Analyse le contexte de : '{data['affirmation']}'.
    Question posée : '{data.get('question_posee', '')}'.
    Sources validées pertinentes (utilise UNIQUEMENT celles-ci) :
    {_sources_for_prompt(selected_sources)}

    ⚠️ ATTENTION CRITIQUE : Cette affirmation peut être un MENSONGE TOTAL. Ne la prends pas pour une vérité absolue.
    
    RÈGLES STRICTES :
    1. analyse_detaillee : Fais une analyse approfondie (environ 5 à 7 phrases) pour expliquer le contexte RÉEL. Si les sources contredisent l'affirmation, explique la vraie situation.
    2. source_index : index numérique de la source principale (1..N).
    
    JSON: {{"agent": "contexte", "analyse_detaillee": "...", "source_index": 1}}"""
    
    raw = await _mistral_json(prompt)
    return _sanitize_primary_source(raw_result=raw, sources=selected_sources)

# --- ROUTEUR (CORRIGÉ POUR DÉTECTER LES MOTS QUANTITATIFS) ---
async def agent_routeur(data):
    prompt = f"""Tu es le routeur d'un système de fact-checking en direct.

    PHRASE ACTUELLE A EVALUER (UNE SEULE PHRASE):
    '{data.get('affirmation', '')}'

    CONTEXTE PRECEDENT (INFO SEULEMENT, NE JAMAIS FACT-CHECKER CETTE PARTIE):
    '{data.get('contexte_precedent', '')}'

    REGLES STRICTES:
    1. Tu fact-checkes UNIQUEMENT la phrase actuelle.
    2. Tu n'as pas le droit de fusionner plusieurs phrases.
    3. Le contexte sert uniquement a detecter une correction, retractation ou redondance.
    4. Si la phrase actuelle corrige/annule une phrase precedente, mets tous les run_* a false.
    5. `affirmation_propre` doit rester une reformulation concise de la phrase actuelle uniquement.

    Routage:
    - 'run_stats' : TRUE pour chiffres, pourcentages, budgets, economie, ou quantifications absolues.
    - 'run_rhetorique' : TRUE si une question a ete posee et que la phrase actuelle esquive.
    - 'run_coherence_personnelle' : TRUE si la phrase actuelle engage la coherence des declarations de la personne.
    - 'run_contexte' : TRUE pour evenement/law/contexte verifiable, mais pas pour un pur chiffre deja traite par stats.

    Renvoie UNIQUEMENT ce JSON strict :
    {{
      "affirmation_propre": "La phrase actuelle reformulee",
      "run_stats": bool,
      "run_rhetorique": bool,
      "run_coherence_personnelle": bool,
      "run_contexte": bool
    }}
    """
    
    return await _mistral_json(prompt)

# --- EXÉCUTEUR PARALLÈLE ---
async def executer_analyse_parallele(data):
    print(f"🚦 PHRASE ACTUELLE : '{data['affirmation'][:60]}...'")
    
    routage = await agent_routeur(data)
    affirmation_propre = routage.get('affirmation_propre', data['affirmation'])
    print(f"✨ TEXTE NETTOYÉ : '{affirmation_propre}'")
    
    data_propre = data.copy()
    data_propre['affirmation'] = affirmation_propre 
    
    taches_a_lancer = []
    if routage.get("run_stats"): taches_a_lancer.append(agent_statistique(data_propre))
    if routage.get("run_rhetorique"): taches_a_lancer.append(agent_rhetorique(data_propre))
    if routage.get("run_coherence_personnelle"): taches_a_lancer.append(agent_coherence_personnelle(data_propre))
    if routage.get("run_contexte"): taches_a_lancer.append(agent_contexte(data_propre))
        
    if not taches_a_lancer:
        return [] 
    
    print(f"🚀 EXÉCUTION : {len(taches_a_lancer)} agent(s) sur l'affirmation propre...")
    rapports = await asyncio.gather(*taches_a_lancer)
    return rapports

# --- LE NOUVEAU RÉDACTEUR EN CHEF (ÉDITEUR) ---
async def agent_editeur(contexte_precedent, affirmation_actuelle, rapports_agents):
    print("📝 [Rédacteur en Chef] Régulation par rapport au contexte global...")
    
    if not rapports_agents:
        return {"afficher_bandeau": False, "raison": "Aucun fact-check nécessaire."}

    prompt = f"""Tu es le Rédacteur en Chef d'une émission politique en direct.
    
    1. HISTORIQUE DE LA DISCUSSION (Les 10 phrases précédentes) :
    "{contexte_precedent}"
    
    2. AFFIRMATION À FACT-CHECKER (L'instant T) :
    "{affirmation_actuelle}"
    
    3. RAPPORTS DÉTAILLÉS DES AGENTS (Brouillons bruts) :
    {json.dumps(rapports_agents, ensure_ascii=False)}

    TA MISSION :
    - Filtre de redondance : Si le fait a déjà été expliqué dans l'historique de la discussion, ou si le fact-check est inutile, mets "afficher_bandeau": false.
    - Verdict Nuancé : Détermine la vérité globale de l'affirmation à l'instant T (ex: Vrai, Faux, Exagéré, Trompeur, À nuancer, Contradictoire).
    - Synthèse TV : Les agents ont fourni de longues analyses. Compresse leur travail en EXACTEMENT DEUX PHRASES concises et percutantes pour l'affichage final, en ajoutant la nuance nécessaire par rapport au contexte.
    - Important: quand tu cites une source dans "explications", fournis TOUJOURS un lien URL HTTP(S) correspondant.
    
    FORMAT JSON STRICT ATTENDU :
    {{
      "afficher_bandeau": true,
      "verdict_global": "Trompeur", // ou Vrai, Faux, À nuancer...
      "explications": {{
         "statistique": {{
            "texte": "Les 2 phrases de synthèse max.",
            "source": "Nom de la source",
            "url": "https://..."
         }},
         "contexte": {{
            "texte": "Les 2 phrases de synthèse max.",
            "source": "Nom de la source",
            "url": "https://..."
         }},
         "rhetorique": "Explication courte si esquive",
         "coherence": {{
            "texte": "Explication courte si contradiction",
            "source": "Nom de la source",
            "url": "https://..."
         }}
      }}
    }}
    NOTE : N'inclus dans 'explications' que les clés des agents qui ont fourni une analyse utile.
    """
    
    return await _mistral_json(prompt)

@activity.defn
async def analyze_debate_line(current_json: dict, last_minute_json: dict) -> dict:
    """
    Activité principale appelée par Temporal pour chaque phrase détectée.
    """
    # 1. Extraction des données du format de ton collègue
    personne = current_json.get("personne", "Intervenant inconnu")
    question = current_json.get("question_posee", "")
    affirmation = _extract_current_affirmation(current_json)
    if not affirmation:
        return {
            "afficher_bandeau": False,
            "raison": "Phrase courante vide.",
        }
    
    # Contexte = phrases precedentes de la derniere minute (sans la phrase courante).
    phrases_contexte = _extract_previous_context_phrases(last_minute_json, affirmation)
    contexte_precedent = " ".join(phrases_contexte)

    # 2. Préparation du dictionnaire pour tes agents
    data_pour_agents = {
        "personne": personne,
        "question_posee": question,
        "affirmation": affirmation,
        "contexte_precedent": contexte_precedent,
    }

    print(
        f"🎤 Analyse en cours pour {personne} "
        f"(phrase_courante='{affirmation[:80]}', contexte_phrases={len(phrases_contexte)})..."
    )

    # 3. Lancement du Pipeline (Routeur -> Experts en parallèle)
    try:
        rapports_bruts = await executer_analyse_parallele(data_pour_agents)
        
        # 4. Régulation par le Rédacteur en Chef (Éditeur)
        # Il utilise le contexte des 60 dernières secondes pour éviter les répétitions
        resultat_final = await agent_editeur(
            contexte_precedent=contexte_precedent,
            affirmation_actuelle=affirmation,
            rapports_agents=rapports_bruts
        )
        if not isinstance(resultat_final, dict):
            return {
                "afficher_bandeau": False,
                "raison": "Resultat editeur invalide.",
            }
        resultat_final = _enrich_editor_result_with_sources(resultat_final, rapports_bruts)
        if resultat_final.get("afficher_bandeau") and not resultat_final.get("sources"):
            resultat_final["afficher_bandeau"] = False
            resultat_final["raison"] = (
                "Fact-check ignore: aucune source pertinente avec lien URL."
            )
            explications = resultat_final.get("explications")
            if isinstance(explications, dict):
                for value in explications.values():
                    if isinstance(value, dict):
                        value.pop("source", None)
                        value.pop("url", None)
        
        return resultat_final

    except Exception as e:
        print(f"❌ Erreur lors de l'analyse : {e}")
        return {
            "afficher_bandeau": False,
            "erreur": str(e)
        }


@activity.defn
async def check_next_phrase_self_correction(
    current_json: dict, next_json: dict | None, last_minute_json: dict
) -> dict:
    """
    Détecte si la phrase suivante corrige / annule la phrase courante.
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
    prompt = f"""Tu es un detecteur de correction en direct.

PHRASE_COURANTE:
"{current_affirmation}"

PHRASE_SUIVANTE:
"{next_affirmation}"

CONTEXTE_PRECEDENT:
"{contexte_precedent}"

Mission:
- Determine si PHRASE_SUIVANTE corrige/retracte explicitement PHRASE_COURANTE.
- Exemples de correction: "je corrige", "je me suis trompe", "non plutot", nouveau chiffre qui remplace le precedent.
- Si PHRASE_SUIVANTE est seulement un ajout, une nouvelle idee ou une reformulation, alors ce n'est PAS une correction.

Renvoie UNIQUEMENT ce JSON strict:
{{
  "next_is_correction": true|false,
  "confidence": 0.0,
  "reason": "court"
}}
"""
    try:
        parsed = await _mistral_json(prompt)
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
        # LLM indisponible (ex: 429 rate limit) -> fallback heuristique déjà calculé.
        return {
            "has_next_phrase": True,
            "next_is_correction": bool(heuristic.get("next_is_correction", False)),
            "confidence": float(heuristic.get("confidence", 0.0)),
            "reason": (
                f"LLM indisponible, fallback heuristique: "
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
    Envoie le résultat du workflow au service stream fact-check.
    """
    url = os.getenv("FACT_CHECK_POST_URL", DEFAULT_FACT_CHECK_POST_URL)

    def _do_post():
        return requests.post(url, json=payload, timeout=10)

    try:
        posted_at_utc = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        )
        response = await asyncio.to_thread(_do_post)
        body_preview = response.text[:1000]
        receiver_timestamp_utc = ""
        try:
            response_json = response.json()
            if isinstance(response_json, dict):
                for key in ("timestamp_utc", "timestamp", "timestampUtc"):
                    value = response_json.get(key)
                    if isinstance(value, str) and value.strip():
                        receiver_timestamp_utc = value.strip()
                        break
        except Exception:
            pass
        return {
            "posted": response.ok,
            "status_code": response.status_code,
            "url": url,
            "posted_at_utc": posted_at_utc,
            "receiver_timestamp_utc": receiver_timestamp_utc,
            "response_body_preview": body_preview,
        }
    except Exception as exc:
        return {
            "posted": False,
            "url": url,
            "posted_at_utc": datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "error": str(exc),
        }


@activity.defn
async def archive_transcript_entry(payload: dict) -> dict:
    return await asyncio.to_thread(archive_transcript_entry_payload, payload)
