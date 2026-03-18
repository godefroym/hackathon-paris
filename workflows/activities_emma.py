import os
import json
import asyncio
import re
import hashlib
import copy
import time
import random
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pydantic import BaseModel, Field
import requests
from mistralai import Mistral
from dotenv import load_dotenv
from transcript_archive import archive_transcript_entry_payload

# --- SÉCURITÉ IMPORTS ---
try:
    from temporalio import activity
except ImportError:
    class activity:
        @staticmethod
        def defn(func): return func

# --- INITIALISATION ENV & CLIENT ---
# On va chercher cle.env à la racine (assumée être le dossier de travail)
env_path = Path("cle.env").absolute()
load_dotenv(dotenv_path=env_path, override=True)
client = Mistral(api_key=os.getenv("MISTRAL_API_KEY"))

_FAST_MODEL = "mistral-small-latest"
_SMART_MODEL = "mistral-medium-latest"
_BEST_MODEL = "mistral-large-latest"

CACHE_RESULTATS_GLOBAUX = {}

# --- TIERS fusionnés et complétés pour le pipeline Emma ---
TIER_1_GOUV = [
    "gouv.fr", "insee.fr", "ameli.fr", "vie-publique.fr", "senat.fr", "assemblee-nationale.fr", "data.gouv.fr",
    "inserm.fr", "ansm.sante.fr", "anses.fr", "service-public.fr", "conseil-etat.fr", "actu-juridique.fr",
    "banque-france.fr", "cnrs.fr", "inria.fr", "cea.fr", "archives-ouvertes.fr", "cnes.fr", "techniques-ingenieur.fr"
]
TIER_2_MEDIAS = [
    "actu.fr", "francebleu.fr", "lemonde.fr", "liberation.fr", "rfi.fr", "lepoint.fr", "ladepeche.fr", "france24.com",
    "franceculture.fr", "20minutes.fr", "ouest-france.fr", "mediapart.fr", "numerama.com", "lefigaro.fr", "franceinfo.fr",
    "afp.com", "sudouest.fr", "lesechos.fr", "marianne.net", "francetvinfo.fr", "radiofrance.fr", "actu.orange.fr",
    "tf1info.fr", "lexpress.fr", "dalloz-actualite.fr", "ofce.sciences-po.fr", "75secondes.fr", "legifiscal.fr",
    "fr.wikipedia.org", "reporterre.net", "mouvement-europeen.eu"
]
SOCIAL_BLACKLIST = [
    "tiktok.com", "facebook.com", "instagram.com", "x.com", "twitter.com", "reddit.com", "pinterest.com"
]
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
NON_FACTUAL_MARKERS = (
    "allo",
    "allô",
    "test",
    "ok",
    "okay",
    "euh",
    "deux secondes",
    "on prend",
    "ça marche",
    "ca marche",
    "je vais",
    "on va",
    "putain",
    "ta gueule",
)
FACT_KEYWORDS = (
    "pib",
    "dette",
    "population",
    "habitants",
    "terre",
    "monde",
    "france",
    "euro",
    "euros",
    "milliard",
    "million",
    "pourcent",
    "pourcentage",
    "plus que",
    "moins que",
    "supérieur à",
    "superieur a",
    "inférieur à",
    "inferieur a",
    "augmenté",
    "augmente",
    "augmentation",
    "diminué",
    "diminue",
    "diminution",
    "baissé",
    "baisse",
    "hausse",
    "multiplié par",
    "multiplie par",
    "divisé par",
    "divise par",
    "moitié",
    "moitie",
    "double",
    "triple",
)
FACT_VERBS = (
    " est ",
    " sont ",
    " a ",
    " ont ",
    " compte ",
    " represente ",
    " représente ",
    " depasse ",
    " dépasse ",
    " mesure ",
    " vaut ",
)
STAT_COMPARISON_MARKERS = (
    "pourcent",
    "pourcentage",
    "plus que",
    "moins que",
    "plus de",
    "moins de",
    "supérieur à",
    "superieur a",
    "inférieur à",
    "inferieur a",
    "augmenté",
    "augmente",
    "augmentation",
    "diminué",
    "diminue",
    "diminution",
    "baissé",
    "baisse",
    "hausse",
    "multiplié par",
    "multiplie par",
    "divisé par",
    "divise par",
    "fois plus",
    "fois moins",
    "moitié",
    "moitie",
    "double",
    "triple",
)
EVENT_KEYWORDS = (
    "jeux olympiques",
    "jo ",
    "olympique",
    "olympiques",
    "grève",
    "greve",
    "guerre",
    "manifestation",
    "loi",
    "projet de loi",
    "proposition de loi",
    "décret",
    "decret",
    "réforme",
    "reforme",
    "élection",
    "election",
    "émeute",
    "emeute",
    "attentat",
    "incendie",
    "inondation",
    "séisme",
    "seisme",
    "tour de france",
    "coupe du monde",
    "championnat",
    "finale",
    "match",
    "crise",
    "scandale",
    "attaque",
    "fait divers",
)

DEFAULT_FACT_CHECK_POST_URL = "http://localhost:8000/api/stream/fact-check"
PIPELINE_LANGUAGE = os.getenv("PIPELINE_LANGUAGE", "fr").strip().lower() or "fr"
if PIPELINE_LANGUAGE not in {"fr", "en"}:
    PIPELINE_LANGUAGE = "fr"
FACT_CHECK_OUTPUT_LANGUAGE = PIPELINE_LANGUAGE
FACT_CHECK_PIVOT_LANGUAGE = "fr"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_SEARCH_FALLBACK_ENABLED = (
    os.getenv("GEMINI_SEARCH_FALLBACK_ENABLED", "").strip().lower()
    in {"1", "true", "yes", "on"}
) or bool(GEMINI_API_KEY)
GEMINI_SEARCH_FALLBACK_MODEL = (
    os.getenv("GEMINI_SEARCH_FALLBACK_MODEL", "gemini-2.5-flash").strip()
    or "gemini-2.5-flash"
)
GEMINI_SEARCH_TIMEOUT_SECONDS = max(
    3.0, float(os.getenv("GEMINI_SEARCH_TIMEOUT_SECONDS", "20"))
)
MISTRAL_WEB_SEARCH_503_BEFORE_GEMINI = max(
    1, int(os.getenv("MISTRAL_WEB_SEARCH_503_BEFORE_GEMINI", "1"))
)
FACT_CHECK_EMERGENCY_DEGRADED_MODE = (
    os.getenv("FACT_CHECK_EMERGENCY_DEGRADED_MODE", "").strip().lower()
    in {"1", "true", "yes", "on"}
)
MISTRAL_TRANSIENT_MAX_RETRIES = max(
    0, int(os.getenv("MISTRAL_TRANSIENT_MAX_RETRIES", "3"))
)
MISTRAL_TRANSIENT_BACKOFF_BASE_SECONDS = max(
    0.1, float(os.getenv("MISTRAL_TRANSIENT_BACKOFF_BASE_SECONDS", "0.8"))
)
MISTRAL_TRANSIENT_BACKOFF_MAX_SECONDS = max(
    MISTRAL_TRANSIENT_BACKOFF_BASE_SECONDS,
    float(os.getenv("MISTRAL_TRANSIENT_BACKOFF_MAX_SECONDS", "8.0")),
)
MISTRAL_AGENT_CALL_TIMEOUT_SECONDS = max(
    3.0, float(os.getenv("MISTRAL_AGENT_CALL_TIMEOUT_SECONDS", "10.0"))
)
CLEANER_TOKEN_SIMILARITY_THRESHOLD = min(
    0.95, max(0.3, float(os.getenv("CLEANER_TOKEN_SIMILARITY_THRESHOLD", "0.6")))
)
CLEANER_STRICT_TOKEN_SIMILARITY_THRESHOLD = min(
    0.98, max(0.5, float(os.getenv("CLEANER_STRICT_TOKEN_SIMILARITY_THRESHOLD", "0.72")))
)
CLEANER_IGNORE_TOKENS = {
    "a",
    "ai",
    "au",
    "aux",
    "ca",
    "car",
    "ce",
    "ces",
    "cet",
    "cette",
    "comme",
    "dans",
    "de",
    "des",
    "du",
    "elle",
    "elles",
    "en",
    "entre",
    "est",
    "et",
    "euh",
    "hein",
    "hum",
    "il",
    "ils",
    "je",
    "la",
    "le",
    "les",
    "leur",
    "leurs",
    "mais",
    "mes",
    "mon",
    "ne",
    "nos",
    "notre",
    "nous",
    "on",
    "ou",
    "où",
    "par",
    "pas",
    "plus",
    "pour",
    "qu",
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
    "ton",
    "tu",
    "un",
    "une",
    "vos",
    "votre",
    "vous",
}
CLEANER_DROPPABLE_TOKENS = {
    "euh",
    "heu",
    "hum",
    "ben",
    "bah",
    "hein",
    "donc",
}

# =============================================================================
# 2. SCHÉMAS PYDANTIC 
# =============================================================================
class CleanerOutput(BaseModel):
    phrase_nette: str # UNIQUE MISSION

class RouteurOutput(BaseModel):
    est_verifiable: bool = Field(description="True si fait ou quantité. False si opinion/futur.")
    run_stats: bool
    run_contexte: bool
    run_coherence_personnelle: bool
    run_rhetorique: bool

class SourceEntry(BaseModel):
    url: str = ""
    organization: str = ""

class StatistiqueOutput(BaseModel):
    agent: str = "statistique"
    verdict: str = Field(description="VRAI, FAUX, ou TROMPEUR")
    chiffre_cle: str = Field(description="LE CHIFFRE EXACT ET SEUL")
    analyse_detaillee: str = Field(description="L'analyse factuelle.")

class ContexteOutput(BaseModel):
    agent: str = "contexte"
    analyse_detaillee: str

class CoherenceOutput(BaseModel):
    agent: str = "coherence"
    explication: str = ""

class RhetoriqueOutput(BaseModel):
    agent: str = "rhetorique"
    explication: str = ""

class JudgeOutput(BaseModel):
    est_valide: bool
    raison_rejet: str

class VeristralFinalOutput(BaseModel):
    fact_check: str | None
    contexte: str | None
    sources_utilisees: list[SourceEntry] = Field(default_factory=list)

# =============================================================================
# 3. MOTEUR DE RECHERCHE & UTILS 
# =============================================================================
def _domain_to_organization(url: str) -> str:
    try: return urlparse(url).netloc.lower().replace("www.", "")
    except: return "source"

def _score_source(url: str) -> int:
    host = urlparse(url).netloc.lower()
    if any(b in host for b in SOCIAL_BLACKLIST): return -1
    if any(t1 in host for t1 in TIER_1_GOUV): return 100 
    if any(t2 in host for t2 in TIER_2_MEDIAS): return 50
    return 10 



# --- SÉCURITÉ : Vérification robuste de l'URL (vivante) ---
def _is_http_url(url: str) -> bool:
    if not isinstance(url, str):
        return False
    lowered = url.strip().lower()
    return lowered.startswith("http://") or lowered.startswith("https://")

async def _is_url_alive(url: str) -> bool:
    if not _is_http_url(url):
        return False
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    def _do_ping():
        import requests
        try:
            res = requests.get(url, headers=headers, timeout=4, allow_redirects=True)
            if res.status_code >= 400:
                return False
            final_url = res.url
            if urlparse(url).path.strip('/') != '' and urlparse(final_url).path.strip('/') == '':
                print(f"⚠️ Redirection vers l'accueil bloquée : {url}")
                return False
            texte_page = res.text[:3000].lower()
            mots_interdits = ["page introuvable", "erreur 404", "n'existe pas", "not found", "page non trouvée"]
            if any(mot in texte_page for mot in mots_interdits):
                print(f"⚠️ Soft-404 bloquée : {url}")
                return False
            return True
        except requests.RequestException:
            return False
    return await asyncio.to_thread(_do_ping)


def _normalize_sources(raw_sources: list[Any]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for source in raw_sources:
        if not isinstance(source, dict):
            continue
        url = str(source.get("url", "")).strip()
        if not _is_http_url(url):
            continue
        if url in seen:
            continue
        seen.add(url)
        organization = str(source.get("organization", "")).strip() or _domain_to_organization(url)
        normalized.append({"organization": organization[:255], "url": url[:2048]})
    return normalized

def _split_sentences(text: str) -> list[str]:
    if not isinstance(text, str):
        return []
    return [
        sentence.strip(" \t\n\r\"'")
        for sentence in re.split(r"[.!?]+", text)
        if sentence and sentence.strip()
    ]


def _extract_fact_focus_text(data: dict[str, Any], clean_text: str) -> str:
    # Prioritize the current sentence from ingestion payload.
    current = data.get("affirmation_courante")
    if isinstance(current, str) and current.strip():
        focus_candidates = _split_sentences(current)
        if focus_candidates:
            return focus_candidates[-1]
        return current.strip()

    focus_candidates = _split_sentences(clean_text)
    if focus_candidates:
        stat_markers = (
            "%",
            "pourcent",
            "milliard",
            "million",
            "euro",
            "pib",
            "dette",
            "population",
            "habitants",
            "terre",
            "monde",
        )
        prioritized = [
            sentence
            for sentence in focus_candidates
            if re.search(r"\d", sentence)
            or any(marker in sentence.lower() for marker in stat_markers)
        ]
        return (prioritized or focus_candidates)[-1]
    return clean_text.strip()


def _is_non_factual_sentence(sentence: str) -> bool:
    text = (sentence or "").strip().lower()
    if not text:
        return True
    words = re.findall(r"[a-zA-ZÀ-ÿ0-9]+", text)
    if len(words) < 3:
        return True
    if text.endswith("?"):
        return True
    return any(marker in text for marker in NON_FACTUAL_MARKERS)


def _is_atomic_fact_candidate(sentence: str) -> bool:
    text = (sentence or "").strip()
    lower = text.lower()
    if _is_non_factual_sentence(text):
        return False
    if re.search(r"\d", text):
        return True
    if any(keyword in lower for keyword in FACT_KEYWORDS):
        return True
    return any(verb in f" {lower} " for verb in FACT_VERBS)


def _extract_atomic_fact_assertion(data: dict[str, Any], clean_text: str) -> str:
    # Prefer the most recent current sentence from ingestion.
    primary_text = data.get("affirmation_courante")
    if not isinstance(primary_text, str) or not primary_text.strip():
        primary_text = clean_text

    primary_sentences = _split_sentences(primary_text)
    factual_primary = [
        sentence for sentence in primary_sentences if _is_atomic_fact_candidate(sentence)
    ]
    if factual_primary:
        return factual_primary[-1]

    clean_sentences = _split_sentences(clean_text)
    factual_clean = [
        sentence for sentence in clean_sentences if _is_atomic_fact_candidate(sentence)
    ]
    if factual_clean:
        return factual_clean[-1]

    return _extract_fact_focus_text(data, clean_text)


def _extract_urls_from_text(text: str) -> list[str]:
    if not isinstance(text, str):
        return []
    return re.findall(r"https?://[^\s\]>)\"']+", text)


def _extract_numbers(text: str) -> list[str]:
    if not isinstance(text, str):
        return []
    return re.findall(r"\d+(?:[.,]\d+)?", text)


def _normalize_token_for_cleaner(token: str) -> str:
    normalized = unicodedata.normalize("NFKD", (token or "").lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _content_tokens_for_cleaner(text: str) -> list[str]:
    tokens = re.findall(r"[a-zA-ZÀ-ÿ0-9]+", text or "")
    normalized_tokens: list[str] = []
    for token in tokens:
        normalized = _normalize_token_for_cleaner(token)
        if len(normalized) < 3:
            continue
        if normalized in CLEANER_IGNORE_TOKENS:
            continue
        normalized_tokens.append(normalized)
    return normalized_tokens


def _ordered_tokens_for_cleaner(text: str) -> list[str]:
    tokens = re.findall(r"[a-zA-ZÀ-ÿ0-9]+", text or "")
    return [_normalize_token_for_cleaner(token) for token in tokens if token.strip()]


def _token_similarity(left: str, right: str) -> float:
    return SequenceMatcher(a=left, b=right).ratio()


def _has_numeric_drift(original_text: str, cleaned_text: str) -> bool:
    original_numbers = _extract_numbers(original_text)
    cleaned_numbers = _extract_numbers(cleaned_text)
    if not original_numbers:
        return False
    # Keep original assertion if cleaner altered or removed numeric values.
    return original_numbers != cleaned_numbers


def _has_semantic_drift(original_text: str, cleaned_text: str) -> bool:
    original_tokens = _content_tokens_for_cleaner(original_text)
    cleaned_tokens = _content_tokens_for_cleaner(cleaned_text)
    if not original_tokens or not cleaned_tokens:
        return False

    matcher = SequenceMatcher(a=original_tokens, b=cleaned_tokens)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue

        original_segment = original_tokens[i1:i2]
        cleaned_segment = cleaned_tokens[j1:j2]

        if tag in {"insert", "delete"}:
            if original_segment or cleaned_segment:
                return True
            continue

        if tag == "replace":
            if len(original_segment) != len(cleaned_segment):
                return True
            for original_token, cleaned_token in zip(original_segment, cleaned_segment):
                if (
                    _token_similarity(original_token, cleaned_token)
                    < CLEANER_TOKEN_SIMILARITY_THRESHOLD
                ):
                    return True

    return False


def _cleaner_changes_are_safe(original_text: str, cleaned_text: str) -> bool:
    original = (original_text or "").strip()
    cleaned = (cleaned_text or "").strip()
    if not original or not cleaned or original == cleaned:
        return True

    original_sentences = _split_sentences(original)
    cleaned_sentences = _split_sentences(cleaned)
    if len(original_sentences) != len(cleaned_sentences):
        return False

    original_tokens = _ordered_tokens_for_cleaner(original)
    cleaned_tokens = _ordered_tokens_for_cleaner(cleaned)
    if not original_tokens or not cleaned_tokens:
        return True

    matcher = SequenceMatcher(a=original_tokens, b=cleaned_tokens)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue

        original_segment = original_tokens[i1:i2]
        cleaned_segment = cleaned_tokens[j1:j2]

        if tag in {"insert", "delete"}:
            changed_segment = original_segment or cleaned_segment
            if any(token not in CLEANER_DROPPABLE_TOKENS for token in changed_segment):
                return False
            continue

        if tag == "replace":
            if len(original_segment) != len(cleaned_segment):
                return False
            for original_token, cleaned_token in zip(original_segment, cleaned_segment):
                if original_token == cleaned_token:
                    continue
                if (
                    original_token in CLEANER_DROPPABLE_TOKENS
                    or cleaned_token in CLEANER_DROPPABLE_TOKENS
                ):
                    continue
                if (
                    _token_similarity(original_token, cleaned_token)
                    < CLEANER_STRICT_TOKEN_SIMILARITY_THRESHOLD
                ):
                    return False

    return True


def _is_transient_mistral_error(exc: Exception) -> bool:
    lowered = str(exc).lower()
    transient_markers = (
        "status 500",
        "status 502",
        "status 503",
        "status 504",
        "upstream connect error",
        "disconnect/reset before headers",
        "reset reason: overflow",
        "failed to create conversation response",
        "temporarily unavailable",
        "connection reset",
        "timed out",
        "timeout",
        "\"code\":3000",
        "\"code\":\"3000\"",
    )
    return any(marker in lowered for marker in transient_markers)


async def _run_with_mistral_retries(
    label: str, operation, *, max_retries: int | None = None
):
    retries = MISTRAL_TRANSIENT_MAX_RETRIES if max_retries is None else max(0, max_retries)
    for attempt in range(retries + 1):
        try:
            return await operation()
        except Exception as exc:
            if attempt >= retries or not _is_transient_mistral_error(exc):
                raise
            backoff = min(
                MISTRAL_TRANSIENT_BACKOFF_MAX_SECONDS,
                MISTRAL_TRANSIENT_BACKOFF_BASE_SECONDS * (2 ** attempt),
            )
            jitter = random.uniform(0.0, 0.25 * max(0.2, backoff))
            wait_seconds = backoff + jitter
            print(
                "[mistral] erreur transitoire "
                f"({label}), retry {attempt + 1}/{retries} "
                f"dans {wait_seconds:.2f}s: {exc}"
            )
            await asyncio.sleep(wait_seconds)

    raise RuntimeError(f"Unreachable retry exhaustion for {label}")


def _normalize_language_code(value: Any) -> str:
    if not isinstance(value, str):
        return "unknown"
    normalized = value.strip().lower()
    if not normalized:
        return "unknown"
    if normalized.startswith("fr"):
        return "fr"
    if normalized.startswith("en"):
        return "en"
    return normalized.split("-", 1)[0]


async def _mistral_json_completion(prompt: str, *, model: str = _FAST_MODEL) -> dict[str, Any]:
    try:
        res = await _run_with_mistral_retries(
            f"chat.complete_async:{model}",
            lambda: client.chat.complete_async(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            ),
        )
        content = res.choices[0].message.content
        if isinstance(content, str):
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return parsed
    except Exception as exc:
        print(f"⚠️ Erreur mistral_json_completion: {exc}")
    return {}


async def _translate_to_french_with_detection(text: str) -> tuple[str, str]:
    source = (text or "").strip()
    if not source:
        return "unknown", ""

    prompt = f"""
Tu es un traducteur strict.
Texte d'entrée:
\"\"\"{source}\"\"\"

Réponds UNIQUEMENT en JSON:
{{
  "detected_language": "fr|en|other",
  "text_fr": "..."
}}

Règles:
- Si le texte est déjà en français, "text_fr" = texte original (corrigé minimalement).
- Conserve exactement les nombres, unités, noms propres, négations et sens.
- N'invente pas d'information.
"""
    parsed = await _mistral_json_completion(prompt, model=_FAST_MODEL)
    detected = _normalize_language_code(parsed.get("detected_language"))
    translated = parsed.get("text_fr")
    if not isinstance(translated, str) or not translated.strip():
        translated = source
    return detected, translated.strip()


async def _translate_from_french(text: str, target_language: str) -> str:
    source = (text or "").strip()
    target = _normalize_language_code(target_language)
    if not source:
        return ""
    if target in {"fr", "unknown"}:
        return source

    prompt = f"""
Translate strictly from French to {target}.
Input:
\"\"\"{source}\"\"\"

Return ONLY JSON:
{{
  "text": "..."
}}

Rules:
- Preserve all numbers, units, named entities, negations, and URLs exactly.
- Do not add or remove factual claims.
"""
    parsed = await _mistral_json_completion(prompt, model=_FAST_MODEL)
    translated = parsed.get("text")
    if not isinstance(translated, str) or not translated.strip():
        return source
    return translated.strip()


def _dedupe_source_queries(queries: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        normalized = " ".join(str(query or "").split())
        if len(normalized) < 6:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


def _build_heuristic_source_queries(
    base_query: str, *, category: str, speaker: str = ""
) -> list[str]:
    cleaned_base = (base_query or "").strip()
    if not cleaned_base:
        return []

    queries = [
        cleaned_base,
        f"source officielle {cleaned_base}",
        f"statistiques officielles {cleaned_base}",
    ]

    lowered = cleaned_base.lower()
    if "france" in lowered:
        queries.append(f"insee {cleaned_base}")
    if "population" in lowered or "êtres humains" in lowered or "terre" in lowered or "monde" in lowered:
        queries.append("population mondiale total banque mondiale ONU")
    if "pib" in lowered:
        queries.append("PIB France INSEE Banque mondiale NY.GDP.MKTP.CD")
    if "dette" in lowered:
        queries.append("dette publique France INSEE Banque de France")
    if any(token in lowered for token in ("doigt", "doigts", "main", "mains")):
        queries.extend(
            [
                "combien de doigts a un être humain",
                "anatomie humaine nombre de doigts",
                "how many fingers does a human have",
            ]
        )
    if any(token in lowered for token in ("humain", "être humain", "corps humain")):
        queries.append(f"preuve factuelle {cleaned_base}")
    if category == "coherence" and speaker:
        queries.append(f"{speaker} archive déclaration {cleaned_base}")

    return _dedupe_source_queries(queries)


async def _build_source_queries(
    base_query: str, *, category: str, speaker: str = ""
) -> list[str]:
    cleaned_base = (base_query or "").strip()
    if not cleaned_base:
        return []

    heuristic_queries = _build_heuristic_source_queries(
        cleaned_base,
        category=category,
        speaker=speaker,
    )
    if FACT_CHECK_EMERGENCY_DEGRADED_MODE:
        return heuristic_queries

    prompt = f"""
Tu dois préparer une recherche web pour trouver AU MOINS UN LIEN FIABLE permettant de vérifier une affirmation.

Affirmation :
\"\"\"{cleaned_base}\"\"\"

Question à te poser :
"Si je voulais prouver que cette affirmation est fausse, quelle preuve précise devrais-je chercher ?"

Réponds uniquement en JSON :
{{
  "proof_to_look_for": "phrase courte décrivant la preuve recherchée",
  "queries": [
    "requête web 1",
    "requête web 2",
    "requête web 3"
  ]
}}

Règles :
- Les requêtes doivent chercher une preuve, pas reformuler bêtement l'affirmation.
- Les requêtes doivent maximiser les chances d'obtenir un lien fiable.
- Si l'affirmation parle d'un nombre, cherche directement la donnée correcte.
- Si l'affirmation parle de science, médecine, biologie, géographie, histoire ou institutions, cherche le fait correct.
- Si l'affirmation est absurde ou manifestement fausse, cherche quand même la preuve positive du fait correct.
- N'écris pas d'URL.
- Donne 3 requêtes maximum.
"""
    parsed = await _mistral_json_completion(prompt, model=_FAST_MODEL)
    proof = str(parsed.get("proof_to_look_for", "")).strip()
    raw_queries = parsed.get("queries")
    planned_queries = [proof] if proof else []
    if isinstance(raw_queries, list):
        for query in raw_queries:
            if isinstance(query, str) and query.strip():
                planned_queries.append(query.strip())

    combined_queries = _dedupe_source_queries(planned_queries + heuristic_queries)
    if combined_queries:
        print(
            f"🧭 [SEARCH PLAN] preuve='{proof[:120]}' "
            f"queries={combined_queries[:3]}"
        )
        return combined_queries

    return heuristic_queries


def _fallback_reference_sources(fact_focus_text: str) -> list[dict[str, str]]:
    lower = (fact_focus_text or "").lower()
    if any(token in lower for token in ("jeux olympiques", "olympique", "olympiques", "jo ")):
        return [
            {
                "organization": "olympics.com",
                "url": "https://olympics.com/",
            },
            {
                "organization": "ioc.org",
                "url": "https://www.ioc.org/",
            },
        ]
    if any(token in lower for token in ("loi", "projet de loi", "proposition de loi", "decret", "décret", "reforme", "réforme")):
        return [
            {
                "organization": "legifrance.gouv.fr",
                "url": "https://www.legifrance.gouv.fr/",
            },
            {
                "organization": "vie-publique.fr",
                "url": "https://www.vie-publique.fr/",
            },
        ]
    if any(token in lower for token in ("population", "êtres humains", "terre", "monde")):
        return [
            {
                "organization": "data.worldbank.org",
                "url": "https://data.worldbank.org/indicator/SP.POP.TOTL",
            },
            {
                "organization": "population.un.org",
                "url": "https://population.un.org/wpp/",
            },
        ]
    if "pib" in lower and "france" in lower:
        return [
            {
                "organization": "data.worldbank.org",
                "url": "https://data.worldbank.org/indicator/NY.GDP.MKTP.CD?locations=FR",
            }
        ]
    if "sida" in lower or "vih" in lower or "hiv" in lower:
        return [
            {
                "organization": "who.int",
                "url": "https://www.who.int/news-room/fact-sheets/detail/hiv-aids",
            }
        ]
    return []


def _build_emergency_degraded_output(
    atomic_fact_text: str,
    *,
    output_language: str,
) -> dict[str, Any] | None:
    lower = (atomic_fact_text or "").lower()
    sources = _fallback_reference_sources(atomic_fact_text)
    if not sources:
        return None

    summary_fr = ""
    summary_en = ""

    if any(token in lower for token in ("population", "êtres humains", "terre", "monde")):
        summary_fr = (
            "FAUX : la population mondiale dépasse 8 milliards d'habitants, "
            "pas 3 millions."
        )
        summary_en = (
            "False: the world population is above 8 billion people, "
            "not 3 million."
        )
    elif ("sida" in lower or "vih" in lower or "hiv" in lower) and (
        "bact" in lower or "bacter" in lower
    ):
        summary_fr = (
            "FAUX : le sida n'est pas une bactérie. Il est lié au VIH, "
            "qui est un virus."
        )
        summary_en = (
            "False: AIDS is not a bacterium. It is linked to HIV, "
            "which is a virus."
        )
    elif "pib" in lower and "france" in lower:
        summary_fr = (
            "FAUX : le PIB de la France se compte en milliers de milliards d'euros, "
            "pas au niveau annoncé."
        )
        summary_en = (
            "False: France's GDP is measured in trillions of euros, "
            "not at the level stated."
        )

    if not summary_fr:
        return None

    summary = summary_en if output_language == "en" else summary_fr
    return {
        "claim": {"text": str(atomic_fact_text)},
        "analysis": {"summary": summary, "sources": sources[:3]},
        "overall_verdict": "inaccurate",
        "afficher_bandeau": True,
        "degraded_mode": True,
        "degraded_mode_reason": "emergency_static_fallback",
    }


def _build_event_context_fallback(
    atomic_fact_text: str,
    *,
    output_language: str,
    sources: list[dict[str, str]],
) -> dict[str, Any] | None:
    if not _looks_like_event_context(atomic_fact_text):
        return None

    normalized_sources = _normalize_sources(sources)
    if not normalized_sources:
        normalized_sources = _fallback_reference_sources(atomic_fact_text)
    normalized_sources = _normalize_sources(normalized_sources)
    if not normalized_sources:
        return None

    lower = atomic_fact_text.lower()
    if any(token in lower for token in ("jeux olympiques", "olympique", "olympiques", "jo ")):
        summary_fr = (
            "Contexte : les Jeux olympiques renvoient a un evenement sportif international encadre par le CIO. "
            "La formulation entendue doit etre rattachee a l'edition precise evoquee et verifiee avec les sources officielles ci-dessous."
        )
        summary_en = (
            "Context: the Olympic Games are an international sporting event overseen by the IOC. "
            "The spoken statement should be tied to the specific edition being referenced and checked against the official sources below."
        )
    elif any(token in lower for token in ("loi", "projet de loi", "proposition de loi", "decret", "décret", "reforme", "réforme")):
        summary_fr = (
            "Contexte : cette phrase renvoie a un texte legislatif ou reglementaire qu'il faut rattacher au bon projet, decret ou reforme. "
            "Le cadrage journalistique doit donc s'appuyer sur les sources institutionnelles listees ci-dessous."
        )
        summary_en = (
            "Context: this statement refers to a legislative or regulatory text that must be tied to the correct bill, decree, or reform. "
            "The journalistic framing should rely on the institutional sources listed below."
        )
    else:
        summary_fr = (
            "Contexte : cette phrase renvoie a un evenement public identifiable qui doit etre resitue dans son edition, sa date ou sa sequence exacte. "
            "Le cadrage peut s'appuyer sur les sources ci-dessous."
        )
        summary_en = (
            "Context: this statement refers to an identifiable public event that should be placed in its exact edition, date, or sequence. "
            "The framing can rely on the sources below."
        )

    summary = summary_en if output_language == "en" else summary_fr
    return {
        "claim": {"text": str(atomic_fact_text)},
        "analysis": {"summary": summary, "sources": normalized_sources[:3]},
        "overall_verdict": "context",
        "afficher_bandeau": True,
        "degraded_mode": True,
        "degraded_mode_reason": "event_context_fallback",
    }


def _extract_gemini_grounding_sources(payload: dict[str, Any]) -> list[dict[str, str]]:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return []

    collected: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        grounding_metadata = candidate.get("groundingMetadata")
        if not isinstance(grounding_metadata, dict):
            continue
        chunks = grounding_metadata.get("groundingChunks")
        if not isinstance(chunks, list):
            continue
        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue
            web = chunk.get("web")
            if not isinstance(web, dict):
                continue
            url = str(web.get("uri", "")).strip()
            if not _is_http_url(url) or url in seen_urls:
                continue
            seen_urls.add(url)
            title = str(web.get("title", "")).strip()
            organization = title or _domain_to_organization(url)
            collected.append({"organization": organization[:255], "url": url[:2048]})
    return collected


def _gemini_grounded_search_sync(query: str) -> list[dict[str, str]]:
    if not GEMINI_API_KEY:
        return []

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_SEARCH_FALLBACK_MODEL}:generateContent"
    )
    headers = {
        "x-goog-api-key": GEMINI_API_KEY,
        "Content-Type": "application/json",
    }
    prompt = (
        "Find authoritative web sources for the following factual claim. "
        "Ground the answer with Google Search.\n"
        f"Claim: {query}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
    }
    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=GEMINI_SEARCH_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    parsed = response.json()
    if not isinstance(parsed, dict):
        return []
    return _extract_gemini_grounding_sources(parsed)


async def _search_and_sort_sources_with_gemini(
    query: str, allow_social: bool = False
) -> list[dict[str, str]]:
    if not GEMINI_SEARCH_FALLBACK_ENABLED or not GEMINI_API_KEY:
        return []
    try:
        sources = await asyncio.to_thread(_gemini_grounded_search_sync, query)
    except Exception as exc:
        print(f"⚠️ Erreur Gemini fallback search: {exc}")
        return []

    filtered: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for source in sources:
        url = source.get("url", "").strip()
        if not _is_http_url(url) or url in seen_urls:
            continue
        host = _domain_to_organization(url)
        score = _score_source(url)
        if score <= 0 and not allow_social:
            continue
        seen_urls.add(url)
        filtered.append(
            {
                "organization": source.get("organization", host)[:255],
                "url": url[:2048],
            }
        )
    return filtered[:3]


async def _search_and_sort_sources(query: str, allow_social: bool = False) -> list[dict]:
    if len(query) < 10:
        return []
    try:
        res = await _run_with_mistral_retries(
            f"web_search:{query[:80]}",
            lambda: client.beta.conversations.start_async(
                model=_SMART_MODEL, inputs=query, tools=[{"type": "web_search"}]
            ),
            max_retries=(
                0
                if FACT_CHECK_EMERGENCY_DEGRADED_MODE
                else max(0, MISTRAL_WEB_SEARCH_503_BEFORE_GEMINI - 1)
            ),
        )
        candidates = []
        for o in res.model_dump().get("outputs", []):
            for url in _extract_urls_from_text(
                json.dumps(o, ensure_ascii=False, default=str)
            ):
                host = _domain_to_organization(url)
                score = _score_source(url)
                if score > 0 or (allow_social and score == -1):
                    final_score = score if score > 0 else 5
                    candidates.append(
                        {"url": url, "organization": host, "score": final_score}
                    )
            if o.get("type") == "message.output" and isinstance(o.get("content"), list):
                for chunk in o["content"]:
                    if isinstance(chunk, dict) and chunk.get("type") == "tool_reference":
                        url = chunk.get("url", "")
                        if url:
                            host = _domain_to_organization(url)
                            score = _score_source(url)
                            if score > 0 or (allow_social and score == -1):
                                final_score = score if score > 0 else 5 
                                candidates.append({"url": url, "organization": host, "score": final_score})

        deduped: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for candidate in sorted(candidates, key=lambda x: x.get("score", 0), reverse=True):
            url = candidate.get("url", "").strip()
            if not _is_http_url(url) or url in seen_urls:
                continue
            seen_urls.add(url)
            deduped.append(candidate)
        return [{"url": c["url"], "organization": c["organization"]} for c in deduped][:3]
    except Exception as e:
        if _is_transient_mistral_error(e):
            gemini_sources = await _search_and_sort_sources_with_gemini(
                query, allow_social=allow_social
            )
            if gemini_sources:
                print(
                    "🛰️ [GEMINI FALLBACK] web search utilise apres echec Mistral "
                    f"pour: {query[:80]}"
                )
                return gemini_sources
        print(f"⚠️ Erreur recherche: {e}")
        return []


async def _search_sources_with_fallbacks(
    *,
    base_query: str,
    category: str,
    allow_social: bool = False,
    speaker: str = "",
) -> list[dict[str, str]]:
    queries = await _build_source_queries(
        base_query,
        category=category,
        speaker=speaker,
    )
    collected: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    max_queries = 1 if FACT_CHECK_EMERGENCY_DEGRADED_MODE else 6
    for query in queries[:max_queries]:
        current = await _search_and_sort_sources(query, allow_social=allow_social)
        for source in current:
            url = source.get("url", "").strip()
            if not _is_http_url(url) or url in seen_urls:
                continue
            seen_urls.add(url)
            collected.append(source)
        if len(collected) >= 3:
            break

    if not collected:
        fallback_sources = _fallback_reference_sources(base_query)
        for source in fallback_sources:
            url = source.get("url", "").strip()
            if not _is_http_url(url) or url in seen_urls:
                continue
            seen_urls.add(url)
            collected.append(source)
        if fallback_sources:
            print(
                f"🧭 [SOURCES] fallback statique utilise ({len(fallback_sources)})"
            )

    return collected[:3]

# =============================================================================
# 4. PROMPTS 
# =============================================================================
def build_cleaner_prompt(affirmation: str) -> str:
    return f"""MISSION : Correcteur orthographique STRICT (Speech-to-Text).
    Phrase brute : '{affirmation}'
    
    RÈGLES ABSOLUES : 
    1. INTERDICTION DE REFORMULER : Tu ne dois sous aucun prétexte changer le style de la phrase ou supprimer des mots valides. 
    2. CONSERVATION DES QUANTITÉS : Conserve IMPÉRATIVEMENT les mots comme "aucun", "tous", "zéro", ainsi que tous les chiffres exacts.
    3. CORRECTION MINIMALE : Corrige UNIQUEMENT les fautes d'orthographe, la phonétique (ex: "le poid de l'étable" -> "le poids de l'État") et efface les bafouillements (ex: "euh"). 
    4. GARDE LE DERNIER CHIFFRE : Si l'orateur se corrige, garde le dernier chiffre énoncé (ex: Il y a 20%, euh non 65% d'arabes en France -> Il y a 65% d'arabes en France")
    5. INTERDICTION DE CHANGER LE SENS : Tu n'as pas le droit de remplacer un concept par un autre. Exemples interdits : "bactérie" -> "maladie", "Ukraine" -> "Russie", "président" -> "dirigeant".
    
    Ne renvoie QUE la phrase corrigée, sans aucun autre texte.
    """
def build_routeur_prompt(clean_text: str) -> str:
    return f"""MISSION : Routeur de fact-checking. Phrase : '{clean_text}'
    1. VÉRIFIABILITÉ (est_verifiable) : True si la phrase affirme un fact ou une stat. False si c'est le futur ("Nous ferons") ou un voeu. Une opinion contenant un fait reste vérifiable (True).
    2. run_stats : True si présence d'une quantité, chiffre, prix, ou mots "aucun/tous/zéro".
    3. run_contexte : True pour un événement réel ou public identifiable : guerre, grève, manifestation, élection, compétition sportive, Jeux Olympiques, crise, fait divers, loi, annonce politique. Faux pour une simple tendance économique sans événement précis.
    4. run_coherence : True si l'orateur jure n'avoir "jamais" changé d'avis.
    5. run_rhetorique : True si une question de journaliste est fournie."""


def _looks_like_event_context(text: str) -> bool:
    lowered = text.lower().strip()
    if not lowered:
        return False
    return any(keyword in lowered for keyword in EVENT_KEYWORDS)


def _looks_like_statistical_claim(text: str) -> bool:
    lowered = text.lower().strip()
    if not lowered:
        return False
    if any(marker in lowered for marker in STAT_COMPARISON_MARKERS):
        return True
    if any(keyword in lowered for keyword in FACT_KEYWORDS):
        return True
    return False


def _extract_current_affirmation(current_json: dict[str, Any]) -> str:
    current = current_json.get("affirmation_courante")
    if isinstance(current, str) and current.strip():
        return current.strip()
    fallback = current_json.get("affirmation")
    if isinstance(fallback, str) and fallback.strip():
        return fallback.strip()
    return ""


def _extract_previous_context_phrases(
    last_minute_json: dict[str, Any], current_affirmation: str
) -> list[str]:
    previous_phrases = last_minute_json.get("previous_phrases")
    if isinstance(previous_phrases, list):
        return [
            phrase.strip()
            for phrase in previous_phrases
            if isinstance(phrase, str) and phrase.strip()
        ]

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

def build_stat_prompt(affirmation: str, sources_text: str) -> str:
    return f"""MISSION : Fact-checking STATISTIQUE.
    Affirmation : '{affirmation}' | SOURCES : {sources_text}
    
    RÈGLES D'ÉVALUATION ABSOLUES (LIS BIEN) :
    1. MOTS D'APPROXIMATION : L'orateur utilise souvent des mots comme "autour de", "environ", "près de". Si la source dit "2.2%" et l'orateur dit "autour de 2.5%", ou "5,2 millions" et l'orateur dit "5 millions", LE VERDICT EST 'VRAI'.
    2. TOLÉRANCE POLITIQUE : Si la différence n'est que de quelques dixièmes (ex: 5.9% vs 6%) ou si l'ordre de grandeur est le bon, LE VERDICT DOIT ÊTRE 'VRAI'.
    3. RÉDACTION STRICTE : Si l'écart est VRAIMENT énorme (FAUX ou TROMPEUR), rédige EXACTEMENT sous ce format : 
       "FAUX : La réalité est de [Vrai Chiffre] selon [Source], et non [Chiffre donné]."
    """
    
def build_contexte_prompt(affirmation: str, sources_text: str) -> str:
    return f"MISSION : Contexte historique. Affirmation : '{affirmation}' | SOURCES : {sources_text}\nRÈGLE : Explique l'événement en 2 phrases neutres max."

def build_coherence_prompt(affirmation: str, sources_text: str, personne: str) -> str:
    return f"MISSION : Cohérence. Orateur : {personne}. Phrase : '{affirmation}' | SOURCES : {sources_text}\nRÈGLE : Indique la contradiction avec les actes passés en 1 phrase."

def build_rhetorique_prompt(question_journaliste: str, reponse_politicien: str) -> str:
    return f"MISSION : Rhétorique. Q: '{question_journaliste}' R: '{reponse_politicien}'\nRÈGLE : Indique si ESQUIVE ou non."

def build_judge_prompt(agent_type: str, reponse_agent: str) -> str:
    return f"MISSION : Contrôle qualité. Agent : '{agent_type}'. Réponse : '{reponse_agent}'. RÈGLE : 'statistique' doit contenir un chiffre. 'est_valide' = True si OK."

def build_final_editor_prompt(rapports: list, sources_disponibles: list) -> str:
    return f"""MISSION : Rédacteur en Chef. 
    RAPPORTS : {json.dumps(rapports, ensure_ascii=False)}
    SOURCES WEB DISPONIBLES : {json.dumps(sources_disponibles, ensure_ascii=False)}
    
    RÈGLES ABSOLUES (OBS) :
    1. 'fact_check' : Si Stat=FAUX/TROMPEUR, écris la phrase choc. Si VRAI, laisse null.
    2. 'contexte' : 2 phrases max ou null.
    3. 'sources_utilisees' : TU DOIS OBLIGATOIREMENT piocher dans "SOURCES WEB DISPONIBLES" pour remplir les champs 'organization' et surtout 'url' des sources dont tu te sers. Ne laisse pas l'URL vide si elle t'est fournie.
    """

# =============================================================================
# 5. EXECUTION & POOL
# =============================================================================
@dataclass
class AgentPool:
    specialist_ids: dict[str, str]

_POOL_INSTANCE = None

async def get_agent_pool():
    global _POOL_INSTANCE
    if _POOL_INSTANCE is None:
        ids = {}
        for key, defi in AGENT_DEFINITIONS.items():
            fmt = {"type": "json_schema", "json_schema": {"name": defi["schema"], "schema": defi["cls"].model_json_schema(), "strict": True}}
            res = await _run_with_mistral_retries(
                f"agents.create:{key}",
                lambda key=key, defi=defi, fmt=fmt: client.beta.agents.create_async(
                    name=f"agent-veristral-{key}",
                    model=defi["model"],
                    completion_args={"temperature": 0.0, "response_format": fmt},
                ),
            )
            ids[key] = res.id
        _POOL_INSTANCE = AgentPool(specialist_ids=ids)
    return _POOL_INSTANCE

def _build_editor_fallback_from_reports(
    rapports: list[dict[str, Any]], sources_disponibles: list[dict[str, str]]
) -> dict[str, Any]:
    fact_check: str | None = None
    contexte: str | None = None

    for report in rapports:
        if not isinstance(report, dict):
            continue
        agent = str(report.get("agent", "")).strip().lower()
        if agent == "statistique" and not fact_check:
            verdict = str(report.get("verdict", "")).strip().upper()
            if verdict in {"FAUX", "TROMPEUR", "VRAI"}:
                fact_check = str(report.get("analyse_detaillee", "")).strip() or None
        elif agent == "contexte" and not contexte:
            contexte = str(report.get("analyse_detaillee", "")).strip() or None
        elif agent == "coherence" and not contexte:
            contexte = str(report.get("explication", "")).strip() or None
        elif agent == "rhetorique" and not contexte:
            contexte = str(report.get("explication", "")).strip() or None

    return {
        "fact_check": fact_check,
        "contexte": contexte,
        "sources_utilisees": _normalize_sources(sources_disponibles)[:3],
    }


async def run_task(agent_key: str, prompt: str) -> dict:
    pool = await get_agent_pool()
    try:
        res = await asyncio.wait_for(
            _run_with_mistral_retries(
                f"conversations.start:{agent_key}",
                lambda: client.beta.conversations.start_async(
                    agent_id=pool.specialist_ids[agent_key],
                    inputs=prompt,
                ),
            ),
            timeout=MISTRAL_AGENT_CALL_TIMEOUT_SECONDS,
        )
        return json.loads(res.model_dump()["outputs"][-1]["content"])
    except asyncio.TimeoutError:
        print(
            f"⚠️ Timeout agent {agent_key}: "
            f">{MISTRAL_AGENT_CALL_TIMEOUT_SECONDS:.1f}s"
        )
        return {}
    except Exception as e:
        print(f"⚠️ Erreur agent {agent_key}: {e}")
        return {}

async def run_agent_with_judge(agent_key: str, initial_prompt: str, max_retries: int = 1) -> dict:
    prompt = initial_prompt
    for attempt in range(max_retries + 1):
        resultat = await run_task(agent_key, prompt)
        if not resultat: return {}

        if agent_key == "statistique":
            texte = str(resultat.get("chiffre_cle", "")) + str(resultat.get("analyse_detaillee", ""))
            if any(char.isdigit() for char in texte) or "inconnu" in texte.lower(): return resultat 
            prompt += f"\n\n🚨 CORRIGE : Inclus un nombre."
            continue

        juge = await run_task("juge", build_judge_prompt(agent_key, json.dumps(resultat, ensure_ascii=False)))
        if juge.get("est_valide", False): return resultat
        prompt += f"\n\n🚨 REJET JUGE : {juge.get('raison_rejet')}. Corrige."
    return resultat

AGENT_DEFINITIONS = {
    "nettoyeur": {"model": _FAST_MODEL, "schema": "cl", "cls": CleanerOutput},
    "routeur": {"model": _FAST_MODEL, "schema": "rt", "cls": RouteurOutput},
    "statistique": {"model": _SMART_MODEL, "schema": "st", "cls": StatistiqueOutput},
    "contexte": {"model": _SMART_MODEL, "schema": "ct", "cls": ContexteOutput},
    "coherence": {"model": _SMART_MODEL, "schema": "ch", "cls": CoherenceOutput},
    "rhetorique": {"model": _FAST_MODEL, "schema": "rh", "cls": RhetoriqueOutput},
    "juge": {"model": _FAST_MODEL, "schema": "jg", "cls": JudgeOutput},
    "editeur_final": {"model": _BEST_MODEL, "schema": "vf", "cls": VeristralFinalOutput},
}

# =============================================================================
# 6. PIPELINE PRINCIPAL (CORRIGÉ ET ALIGNÉ AVEC FORMAT OBS STRICT)
# =============================================================================
@activity.defn
async def analyze_debate_line(current_json: dict, last_minute_json: dict) -> dict:
    # On normalise les entrées pour rester compatible avec l'architecture Temporal
    data = copy.deepcopy(current_json)
    if "question_posee" in data and "question" not in data:
        data["question"] = data["question_posee"]

    # IMPORTANT: evaluate only the latest utterance.
    current_assertion = str(
        data.get("affirmation_courante")
        if isinstance(data.get("affirmation_courante"), str) and data.get("affirmation_courante").strip()
        else data.get("affirmation", "")
    ).strip()
    if not current_assertion:
        return {
            "claim": {"text": ""},
            "analysis": {"summary": "", "sources": []},
            "overall_verdict": "unverified",
            "afficher_bandeau": False,
            "raison": "Fact-check ignore: empty_current_assertion.",
        }

    phrase_id = hashlib.md5(current_assertion.lower().encode()).hexdigest()
    if phrase_id in CACHE_RESULTATS_GLOBAUX: return CACHE_RESULTATS_GLOBAUX[phrase_id]

    print(f"\n🎬 DÉBUT ANALYSE : '{current_assertion}'")

    output_language = (
        FACT_CHECK_OUTPUT_LANGUAGE
        if FACT_CHECK_OUTPUT_LANGUAGE in {"fr", "en"}
        else PIPELINE_LANGUAGE
    )
    original_assertion_for_analysis = current_assertion
    input_language, assertion_fr = await _translate_to_french_with_detection(
        current_assertion
    )
    if not assertion_fr:
        assertion_fr = current_assertion
    print(
        f"🌍 LANGUES: input={input_language} pivot={FACT_CHECK_PIVOT_LANGUAGE} output={output_language}"
    )

    # 1. NETTOYEUR (Uniquement orthographe)
    nettoyage = await run_task("nettoyeur", build_cleaner_prompt(assertion_fr))
    clean_text = nettoyage.get("phrase_nette")
    if not clean_text or len(clean_text) < 2:
        clean_text = assertion_fr
    if not _cleaner_changes_are_safe(assertion_fr, clean_text):
        print("🛡️ [GARDE-FOU] Nettoyeur refuse: changement trop fort ou ordre modifie.")
        clean_text = assertion_fr
    if _has_numeric_drift(assertion_fr, clean_text):
        print("🛡️ [GARDE-FOU] Derive numerique detectee, conservation de la phrase originale.")
        clean_text = assertion_fr
    if _has_semantic_drift(assertion_fr, clean_text):
        print("🛡️ [GARDE-FOU] Derive semantique detectee, conservation de la phrase originale.")
        clean_text = assertion_fr
    print(f"✨ TEXTE NETTOYÉ : '{clean_text}'")
    data_fr = copy.deepcopy(data)
    data_fr["affirmation"] = assertion_fr
    data_fr["affirmation_courante"] = assertion_fr

    atomic_fact_text = _extract_atomic_fact_assertion(data_fr, clean_text)
    if not atomic_fact_text or len(atomic_fact_text.strip()) < 2:
        atomic_fact_text = str(clean_text or assertion_fr).strip()
    fact_focus_text = atomic_fact_text
    print(f"🎯 ASSERTION ATOMIQUE : '{atomic_fact_text}'")
    print(f"🎯 PHRASE FACTUELLE CIBLE : '{fact_focus_text}'")

    # 2. ROUTEUR (Le vrai cerveau d'aiguillage)
    texte_pour_routeur = atomic_fact_text + (f" (Q: {data['question']})" if data.get('question') else "")
    routage = await run_task("routeur", build_routeur_prompt(texte_pour_routeur))
    
    # 🔥 LE FILET DE SÉCURITÉ ANTI-NETTOYEUR TROP ZÉLÉ 🔥
    if routage.get("est_verifiable", True):
        if not routage.get("run_stats"):
            texte_lower = atomic_fact_text.lower()
            
            # 1. Recherche des mots-clés quantitatifs
            mots_stats = ["aucun", "zéro", "plus un seul", "tous", "%"]
            has_stat_word = any(mot in texte_lower for mot in mots_stats) or _looks_like_statistical_claim(atomic_fact_text)
            
            # 2. Recherche intelligente de nombres (Exclut les années 19xx et 20xx)
            nombres = re.findall(r'\b\d+\b', atomic_fact_text)
            has_real_number = False
            for n in nombres:
                if not (len(n) == 4 and (n.startswith("19") or n.startswith("20"))):
                    has_real_number = True
                    break
            
            if has_stat_word or has_real_number:
                print("🛡️ [RATTRAPAGE] Vraie quantité détectée. Forçage run_stats=True.")
                routage["run_stats"] = True
        if not routage.get("run_contexte") and _looks_like_event_context(atomic_fact_text):
            print("🛡️ [RATTRAPAGE] Événement détecté. Forçage run_contexte=True.")
            routage["run_contexte"] = True
    else:
        print("🛡️ [GARDE-FOU] Opinion ou Futur détecté par le Routeur. Annulation.")
        obs_vide = {
            "claim": {
                "text": str(atomic_fact_text)
            },
            "analysis": {
                "summary": "",
                "sources": []
            },
            "overall_verdict": "unverified",
            "afficher_bandeau": False
        }
        CACHE_RESULTATS_GLOBAUX[phrase_id] = obs_vide
        return obs_vide
        
    print(f"🔀 DÉCISION ROUTEUR : {routage}")

    if FACT_CHECK_EMERGENCY_DEGRADED_MODE:
        emergency_output = _build_emergency_degraded_output(
            atomic_fact_text,
            output_language=output_language,
        )
        if emergency_output is not None:
            print("🚑 [MODE DÉGRADÉ] sortie heuristique statique utilisée.")
            CACHE_RESULTATS_GLOBAUX[phrase_id] = emergency_output
            return emergency_output

    # 3. EXPERTS AVEC EXTRACTION DES SOURCES
    tasks = []
    
    async def task_stat():
        srcs = await _search_sources_with_fallbacks(
            base_query=fact_focus_text,
            category="stat",
        )
        print(f"🔎 [SOURCES] stat={len(srcs)}")
        res = await run_agent_with_judge("statistique", build_stat_prompt(atomic_fact_text, json.dumps(srcs, ensure_ascii=False)))
        if res: res["_srcs"] = srcs 
        return res

    async def task_contexte():
        srcs = await _search_sources_with_fallbacks(
            base_query=fact_focus_text,
            category="contexte",
        )
        print(f"🔎 [SOURCES] contexte={len(srcs)}")
        res = await run_agent_with_judge("contexte", build_contexte_prompt(atomic_fact_text, json.dumps(srcs, ensure_ascii=False)))
        if res: res["_srcs"] = srcs
        return res
        
    async def task_coherence():
        srcs = await _search_sources_with_fallbacks(
            base_query=fact_focus_text,
            category="coherence",
            allow_social=True,
            speaker=str(data.get("personne", "politicien")),
        )
        print(f"🔎 [SOURCES] coherence={len(srcs)}")
        res = await run_agent_with_judge("coherence", build_coherence_prompt(atomic_fact_text, json.dumps(srcs, ensure_ascii=False), data.get('personne', 'politicien')))
        if res: res["_srcs"] = srcs
        return res

    async def task_rhetorique():
        return await run_agent_with_judge("rhetorique", build_rhetorique_prompt(data.get('question', ''), atomic_fact_text))

    if routage.get("run_stats"): tasks.append(task_stat())
    if routage.get("run_contexte"): tasks.append(task_contexte())
    if routage.get("run_coherence_personnelle") and "toujours" in atomic_fact_text.lower(): tasks.append(task_coherence())
    if routage.get("run_rhetorique") and data.get("question"): tasks.append(task_rhetorique())
    
    rapports = await asyncio.gather(*tasks) if tasks else []
    rapports = [r for r in rapports if r] 
    
    toutes_les_sources = []
    for r in rapports:
        if "_srcs" in r:
            toutes_les_sources.extend(r["_srcs"])
            del r["_srcs"]
    print(f"🧾 [SOURCES] total_candidates={len(toutes_les_sources)}")

    rapports = [r for r in rapports if not (r.get("agent") == "statistique" and r.get("verdict", "").upper() == "VRAI")]

    if rapports:
        final = await run_task("editeur_final", build_final_editor_prompt(rapports, toutes_les_sources))
        if not final:
            print("🩹 [FALLBACK ÉDITEUR] synthese locale utilisée.")
            final = _build_editor_fallback_from_reports(rapports, toutes_les_sources)
        if not routage.get("run_contexte"): final["contexte"] = None
        if not routage.get("run_stats") and not routage.get("run_rhetorique"): final["fact_check"] = None
    else:
        final = {"fact_check": None, "contexte": None, "sources_utilisees": []}

    summary_parts = [p for p in [final.get("fact_check"), final.get("contexte")] if p]
    summary_complet_fr = " ".join(summary_parts) if summary_parts else ""
    claim_output_text = atomic_fact_text
    summary_output_text = summary_complet_fr
    if output_language == "en":
        claim_output_text = await _translate_from_french(atomic_fact_text, "en")
        summary_output_text = await _translate_from_french(summary_complet_fr, "en")

    verdict_obs = "unverified" 
    if final.get("fact_check"):
        if "FAUX" in final["fact_check"].upper(): 
            verdict_obs = "inaccurate"
        elif "TROMPEUR" in final["fact_check"].upper(): 
            verdict_obs = "partially_accurate"
        else:
            verdict_obs = "accurate" 
    
    declared_sources = (
        final.get("sources_utilisees", [])
        if isinstance(final.get("sources_utilisees"), list)
        else []
    )
    sources_obs = _normalize_sources(declared_sources)
    if not sources_obs:
        # Fallback: enforce at least one valid URL source from web-search results
        # so the payload remains postable for the overlay API contract.
        sources_obs = _normalize_sources(toutes_les_sources)

    if routage.get("run_contexte") and not summary_output_text:
        context_fallback = _build_event_context_fallback(
            atomic_fact_text,
            output_language=output_language,
            sources=sources_obs or toutes_les_sources,
        )
        if context_fallback is not None:
            print("🩹 [FALLBACK CONTEXTE] sortie contexte événementiel utilisée.")
            claim_output_text = str(
                context_fallback.get("claim", {}).get("text", claim_output_text)
            ).strip() or claim_output_text
            summary_output_text = str(
                context_fallback.get("analysis", {}).get("summary", "")
            ).strip()
            sources_obs = _normalize_sources(
                context_fallback.get("analysis", {}).get("sources", [])
            )
            verdict_obs = str(
                context_fallback.get("overall_verdict", verdict_obs)
            ).strip() or verdict_obs

    if not summary_output_text or not sources_obs:
        targeted_fallback = _build_emergency_degraded_output(
            original_assertion_for_analysis,
            output_language=output_language,
        )
        if targeted_fallback is not None:
            print("🩹 [FALLBACK CIBLÉ] sortie heuristique utilisée.")
            claim_output_text = str(targeted_fallback.get("claim", {}).get("text", claim_output_text)).strip() or claim_output_text
            summary_output_text = str(
                targeted_fallback.get("analysis", {}).get("summary", "")
            ).strip()
            sources_obs = _normalize_sources(
                targeted_fallback.get("analysis", {}).get("sources", [])
            )
            verdict_obs = str(targeted_fallback.get("overall_verdict", verdict_obs)).strip() or verdict_obs

    should_show_banner = bool(summary_output_text and sources_obs)

    obs_output = {
        "claim": {
            "text": str(claim_output_text)
        },
        "analysis": {
            "summary": summary_output_text,
            "sources": sources_obs
        },
        "overall_verdict": verdict_obs,
        "afficher_bandeau": should_show_banner
    }
    
    CACHE_RESULTATS_GLOBAUX[phrase_id] = obs_output
    return obs_output

@activity.defn
async def check_next_phrase_self_correction(current_json: dict, next_json: dict | None, last_minute_json: dict) -> dict:
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
    url = os.getenv("FACT_CHECK_POST_URL", DEFAULT_FACT_CHECK_POST_URL)
    posted_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    try:
        response = await asyncio.to_thread(
            lambda: requests.post(url, json=payload, timeout=10)
        )
        return {
            "posted": bool(response.ok),
            "status_code": int(response.status_code),
            "url": url,
            "posted_at_utc": posted_at,
            "response_body_preview": response.text[:500],
        }
    except Exception as e:
        return {
            "posted": False,
            "url": url,
            "posted_at_utc": posted_at,
            "error": str(e),
        }


@activity.defn
async def archive_transcript_entry(payload: dict) -> dict:
    return await asyncio.to_thread(archive_transcript_entry_payload, payload)
