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

DEFAULT_FACT_CHECK_POST_URL = "http://localhost:8000/api/stream/fact-check"

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

async def _search_and_sort_sources(query: str, allow_social: bool = False) -> list[dict]:
    if len(query) < 10: return []
    try:
        res = await client.beta.conversations.start_async(
            model=_SMART_MODEL, inputs=query, tools=[{"type": "web_search"}]
        )
        candidates = []
        for o in res.model_dump().get("outputs", []):
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
                                
        candidates.sort(key=lambda x: x.get("score", 0), reverse=True)
        return [{"url": c["url"], "organization": c["organization"]} for c in candidates][:3] 
    except Exception as e:
        print(f"⚠️ Erreur recherche: {e}")
        return []

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
        
    phrase_id = hashlib.md5(data.get('affirmation', '').strip().lower().encode()).hexdigest()
    if phrase_id in CACHE_RESULTATS_GLOBAUX: return CACHE_RESULTATS_GLOBAUX[phrase_id]

    print(f"\n🎬 DÉBUT ANALYSE : '{data.get('affirmation', '')}'")

    # 1. NETTOYEUR (Uniquement orthographe)
    nettoyage = await run_task("nettoyeur", build_cleaner_prompt(data.get('affirmation', '')))
    clean_text = nettoyage.get("phrase_nette")
    if not clean_text or len(clean_text) < 2: clean_text = data.get('affirmation', '')
    print(f"✨ TEXTE NETTOYÉ : '{clean_text}'")

    # 2. ROUTEUR (Le vrai cerveau d'aiguillage)
    texte_pour_routeur = clean_text + (f" (Q: {data['question']})" if data.get('question') else "")
    routage = await run_task("routeur", build_routeur_prompt(texte_pour_routeur))
    
    # 🔥 LE FILET DE SÉCURITÉ ANTI-NETTOYEUR TROP ZÉLÉ 🔥
    if routage.get("est_verifiable", True):
        if not routage.get("run_stats"):
            texte_lower = data.get('affirmation', '').lower()
            
            # 1. Recherche des mots-clés quantitatifs
            mots_stats = ["aucun", "zéro", "plus un seul", "tous", "%", "pourcent"]
            has_stat_word = any(mot in texte_lower for mot in mots_stats)
            
            # 2. Recherche intelligente de nombres (Exclut les années 19xx et 20xx)
            nombres = re.findall(r'\b\d+\b', data.get('affirmation', ''))
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
                "text": str(data.get('affirmation', ''))
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
        srcs = await _search_and_sort_sources(f"statistiques officielles France {clean_text}")
        res = await run_agent_with_judge("statistique", build_stat_prompt(clean_text, json.dumps(srcs, ensure_ascii=False)))
        if res: res["_srcs"] = srcs 
        return res

    async def task_contexte():
        srcs = await _search_and_sort_sources(f"contexte factuel {clean_text}")
        res = await run_agent_with_judge("contexte", build_contexte_prompt(clean_text, json.dumps(srcs, ensure_ascii=False)))
        if res: res["_srcs"] = srcs
        return res
        
    async def task_coherence():
        srcs = await _search_and_sort_sources(f"archives {data.get('personne', 'politicien')} {clean_text}", allow_social=True)
        res = await run_agent_with_judge("coherence", build_coherence_prompt(clean_text, json.dumps(srcs, ensure_ascii=False), data.get('personne', 'politicien')))
        if res: res["_srcs"] = srcs
        return res

    async def task_rhetorique():
        return await run_agent_with_judge("rhetorique", build_rhetorique_prompt(data.get('question', ''), clean_text))

    if routage.get("run_stats"): tasks.append(task_stat())
    if routage.get("run_contexte"): tasks.append(task_contexte())
    if routage.get("run_coherence_personnelle") and "toujours" in clean_text.lower(): tasks.append(task_coherence())
    if routage.get("run_rhetorique") and data.get("question"): tasks.append(task_rhetorique())
    
    rapports = await asyncio.gather(*tasks) if tasks else []
    rapports = [r for r in rapports if r] 
    
    toutes_les_sources = []
    for r in rapports:
        if "_srcs" in r:
            toutes_les_sources.extend(r["_srcs"])
            del r["_srcs"]

    rapports = [r for r in rapports if not (r.get("agent") == "statistique" and r.get("verdict", "").upper() == "VRAI")]

    if rapports:
        final = await run_task("editeur_final", build_final_editor_prompt(rapports, toutes_les_sources))
        if not routage.get("run_contexte"): final["contexte"] = None
        if not routage.get("run_stats") and not routage.get("run_rhetorique"): final["fact_check"] = None
    else:
        final = {"fact_check": None, "contexte": None, "sources_utilisees": []}

    summary_parts = [p for p in [final.get("fact_check"), final.get("contexte")] if p]
    summary_complet = " ".join(summary_parts) if summary_parts else ""

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

    should_show_banner = bool(summary_complet and sources_obs)

    obs_output = {
        "claim": {
            "text": str(clean_text)
        },
        "analysis": {
            "summary": summary_complet,
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
