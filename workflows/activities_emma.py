import os
import json
import asyncio
import re
import hashlib
import copy
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from dataclasses import dataclass, field
from pydantic import BaseModel, Field
import requests
from mistralai import Mistral
from dotenv import load_dotenv

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

try:
    from activities import (
        check_next_phrase_self_correction as _local_check_next_phrase_self_correction,
    )
except Exception:
    _local_check_next_phrase_self_correction = None

_FAST_MODEL = "mistral-small-latest"
_SMART_MODEL = "mistral-medium-latest"
_BEST_MODEL = "mistral-large-latest"

CACHE_RESULTATS_GLOBAUX = {}
TIER_1_GOUV = ["gouv.fr", "insee.fr", "senat.fr", "assemblee-nationale.fr", "vie-publique.fr", "data.gouv.fr", "ameli.fr", "inserm.fr","ansm.sante.fr","anses.fr","service-publics.fr","conseil-etat.fr","actu-juridique.fr","banque-france.fr","cnrs.fr","iniria.fr","cea.fr","archives-ouvertes.fr","cnes.fr","techniques-ingenieur.fr"]
TIER_2_MEDIAS = ["lemonde.fr", "lefigaro.fr", "liberation.fr", "humanite.fr", "marianne.net", "francetvinfo.fr", "radiofrance.fr", "lesechos.fr", "ouest-france.fr", "france24.com", "franceinfo.fr", "20minutes.fr", "actu.orange.fr", "tf1info.fr","lexpress.fr","dalloz-actualite.fr","ofce.sciences-po.fr","75secondes.fr","legifiscal.fr","fr.wikipedia.org","reporterre.net","mouvement-europeen.eu"]
SOCIAL_BLACKLIST = ["tiktok.com", "facebook.com", "instagram.com", "x.com", "twitter.com", "youtube.com", "linkedin.com", "reddit.com", "pinterest.com", "4chan.org"]
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

DEFAULT_FACT_CHECK_POST_URL = "http://localhost:8000/api/stream/fact-check"
PIPELINE_LANGUAGE = os.getenv("PIPELINE_LANGUAGE", "fr").strip().lower() or "fr"
if PIPELINE_LANGUAGE not in {"fr", "en"}:
    PIPELINE_LANGUAGE = "fr"
FACT_CHECK_OUTPUT_LANGUAGE = PIPELINE_LANGUAGE
FACT_CHECK_PIVOT_LANGUAGE = "fr"

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


def _is_http_url(url: str) -> bool:
    if not isinstance(url, str):
        return False
    lowered = url.strip().lower()
    return lowered.startswith("http://") or lowered.startswith("https://")


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


def _has_numeric_drift(original_text: str, cleaned_text: str) -> bool:
    original_numbers = _extract_numbers(original_text)
    cleaned_numbers = _extract_numbers(cleaned_text)
    if not original_numbers:
        return False
    # Keep original assertion if cleaner altered or removed numeric values.
    return original_numbers != cleaned_numbers


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
        res = await client.chat.complete_async(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
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


def _build_source_queries(base_query: str, *, category: str, speaker: str = "") -> list[str]:
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
    if category == "coherence" and speaker:
        queries.append(f"{speaker} archive déclaration {cleaned_base}")

    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        normalized = " ".join(query.split())
        if len(normalized) < 10:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


def _fallback_reference_sources(fact_focus_text: str) -> list[dict[str, str]]:
    lower = (fact_focus_text or "").lower()
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
    return []


async def _search_and_sort_sources(query: str, allow_social: bool = False) -> list[dict]:
    if len(query) < 10:
        return []
    try:
        res = await client.beta.conversations.start_async(
            model=_SMART_MODEL, inputs=query, tools=[{"type": "web_search"}]
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
        print(f"⚠️ Erreur recherche: {e}")
        return []


async def _search_sources_with_fallbacks(
    *,
    base_query: str,
    category: str,
    allow_social: bool = False,
    speaker: str = "",
) -> list[dict[str, str]]:
    queries = _build_source_queries(base_query, category=category, speaker=speaker)
    collected: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    for query in queries[:6]:
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
    
    Ne renvoie QUE la phrase corrigée, sans aucun autre texte.
    """
def build_routeur_prompt(clean_text: str) -> str:
    return f"""MISSION : Routeur de fact-checking. Phrase : '{clean_text}'
    1. VÉRIFIABILITÉ (est_verifiable) : True si la phrase affirme un fact ou une stat. False si c'est le futur ("Nous ferons") ou un voeu. Une opinion contenant un fait reste vérifiable (True).
    2. run_stats : True si présence d'une quantité, chiffre, prix, ou mots "aucun/tous/zéro".
    3. run_contexte : True UNIQUEMENT pour un événement historique, guerre ou loi. 🚨 Faux pour l'économie.
    4. run_coherence : True si l'orateur jure n'avoir "jamais" changé d'avis.
    5. run_rhetorique : True si une question de journaliste est fournie."""

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
            res = await client.beta.agents.create_async(
                name=f"agent-veristral-{key}", model=defi["model"], completion_args={"temperature": 0.0, "response_format": fmt}
            )
            ids[key] = res.id
        _POOL_INSTANCE = AgentPool(specialist_ids=ids)
    return _POOL_INSTANCE

async def run_task(agent_key: str, prompt: str) -> dict:
    pool = await get_agent_pool()
    try:
        res = await client.beta.conversations.start_async(agent_id=pool.specialist_ids[agent_key], inputs=prompt)
        return json.loads(res.model_dump()["outputs"][-1]["content"])
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
    if _has_numeric_drift(assertion_fr, clean_text):
        print("🛡️ [GARDE-FOU] Derive numerique detectee, conservation de la phrase originale.")
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
            mots_stats = ["aucun", "zéro", "plus un seul", "tous", "%", "pourcent"]
            has_stat_word = any(mot in texte_lower for mot in mots_stats)
            
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
    if _local_check_next_phrase_self_correction is None:
        return {
            "has_next_phrase": bool(next_json),
            "next_is_correction": False,
            "confidence": 0.0,
            "reason": "Fallback: local correction detector unavailable.",
        }
    return await _local_check_next_phrase_self_correction(
        current_json,
        next_json,
        last_minute_json,
    )

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
