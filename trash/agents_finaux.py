import os
import json
import asyncio
import re
import hashlib
import copy
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from dataclasses import dataclass, field
from pydantic import BaseModel, Field
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
env_path = Path("cle.env").absolute()
load_dotenv(dotenv_path=env_path, override=True)
client = Mistral(api_key=os.getenv("MISTRAL_API_KEY"))

_FAST_MODEL = "mistral-small-latest"
_SMART_MODEL = "mistral-medium-latest"
_BEST_MODEL = "mistral-large-latest"

CACHE_RESULTATS_GLOBAUX = {}

# --- PYRAMIDE DES SOURCES (TIERS) ---
TIER_1_GOUV = ["gouv.fr", "insee.fr", "senat.fr", "assemblee-nationale.fr", "vie-publique.fr", "data.gouv.fr", "ameli.fr", "inserm.fr","ansm.sante.fr","anses.fr","service-publics.fr","conseil-etat.fr","actu-juridique.fr","banque-france.fr","cnrs.fr","iniria.fr","cea.fr","archives-ouvertes.fr","cnes.fr","techniques-ingenieur.fr"]
TIER_2_MEDIAS = ["lemonde.fr", "lefigaro.fr", "liberation.fr", "humanite.fr", "marianne.net", "francetvinfo.fr", "radiofrance.fr", "lesechos.fr", "ouest-france.fr", "france24.com", "franceinfo.fr", "20minutes.fr", "actu.orange.fr", "tf1info.fr","lexpress.fr","dalloz-actualite.fr"]
SOCIAL_BLACKLIST = ["tiktok.com", "facebook.com", "instagram.com", "x.com", "twitter.com", "youtube.com", "linkedin.com", "reddit.com", "pinterest.com", "4chan.org"]

# --- FONCTIONS UTILITAIRES DE RECHERCHE ---
def _domain_to_organization(url: str) -> str:
    """Extrait le nom de domaine principal pour l'affichage propre."""
    try: 
        return urlparse(url).netloc.lower().replace("www.", "")
    except: 
        return "source"

def _score_source(url: str) -> int:
    """Attribue un score à l'URL pour la pyramide de fiabilité."""
    host = urlparse(url).netloc.lower()
    if any(b in host for b in SOCIAL_BLACKLIST): return -1
    if any(t1 in host for t1 in TIER_1_GOUV): return 100  # Priorité absolue (Or)
    if any(t2 in host for t2 in TIER_2_MEDIAS): return 50 # Excellente fiabilité (Argent)
    return 10 # Reste du web (Bronze)

async def _search_and_sort_sources(query: str) -> list[dict]:
    """Recherche web via Mistral, extraction et tri pyramidal des sources."""
    if len(query) < 10: 
        return []
        
    try:
        # 1. Appel au moteur de recherche intégré de Mistral
        res = await client.beta.conversations.start_async(
            model=_SMART_MODEL, 
            inputs=query, 
            tools=[{"type": "web_search"}]
        )
        
        candidates = []
        
        # 2. Extraction des URLs retournées par l'outil
        for o in res.model_dump().get("outputs", []):
            if o.get("type") == "message.output" and isinstance(o.get("content"), list):
                for chunk in o["content"]:
                    if isinstance(chunk, dict) and chunk.get("type") == "tool_reference":
                        url = chunk.get("url", "")
                        if url:
                            host = _domain_to_organization(url)
                            candidates.append({"url": url, "organization": host})
                            
        # 3. Filtrage et tri pyramidal
        valid_sources = [c for c in candidates if _score_source(c["url"]) > 0]
        valid_sources.sort(key=lambda x: _score_source(x["url"]), reverse=True)
        
        # 4. On garde uniquement l'élite (le Top 3)
        return valid_sources[:3] 
        
    except Exception as e:
        print(f"⚠️ Erreur lors de la recherche web: {e}")
        return []

        # =============================================================================
# 2. SCHÉMAS PYDANTIC (ARCHITECTURE MULTI-AGENTS & JUGE)
# =============================================================================
from pydantic import BaseModel, Field

# --- 1. LE NETTOYEUR (Nouveau) ---
class CleanerOutput(BaseModel):
    phrase_nettoyee: str = Field(description="L'affirmation brute corrigée phonétiquement.")
    contient_evenement: bool = Field(description="True si la phrase mentionne un événement matériel précis.")
    est_verifiable: bool = Field(description="True si la phrase contient un fait concret ou une stat. False si c'est une opinion, un jugement de valeur ou un superlatif abstrait (ex: 'la plus grande richesse').")

# --- 2. LE ROUTEUR (Simplifié) ---
class RouteurOutput(BaseModel):
    run_stats: bool = Field(description="True si l'affirmation contient ou nécessite un chiffre, un pourcentage ou une quantité.")
    run_contexte: bool = Field(description="True si l'affirmation nécessite des explications historiques ou factuelles.")
    run_coherence_personnelle: bool = Field(description="True si on doit vérifier si la personne a changé d'avis.")
    run_rhetorique: bool = Field(description="True si c'est purement une figure de style ou de l'exagération politique.")

# --- 3. LES EXPERTS (Spécialistes) ---
class SourceEntry(BaseModel):
    url: str = ""
    organization: str = ""

class StatistiqueOutput(BaseModel):
    agent: str = "statistique"
    verdict: str = Field(description="VRAI, FAUX, ou TROMPEUR")
    chiffre_cle: str = Field(description="LE CHIFFRE EXACT ET SEUL (ex: '330000', '70%', '0'). Obligatoire.")
    analyse_detaillee: str = Field(description="L'analyse factuelle contenant le contexte du chiffre (max 15 mots).")
    sources: list[SourceEntry] = Field(default_factory=list)

class ContexteOutput(BaseModel):
    agent: str = "contexte"
    analyse_detaillee: str = Field(description="Explication du contexte historique ou factuel de l'événement.")
    sources: list[SourceEntry] = Field(default_factory=list)

class CoherenceOutput(BaseModel):
    agent: str = "coherence"
    explication: str = ""
    sources: list[SourceEntry] = Field(default_factory=list)

class RhetoriqueOutput(BaseModel):
    agent: str = "rhetorique"
    explication: str = ""

# --- 4. LE JUGE (Nouveau - Boucle de Rétroaction) ---
class JudgeOutput(BaseModel):
    est_valide: bool = Field(description="True si la réponse de l'expert répond parfaitement à la question, False sinon.")
    raison_rejet: str = Field(description="Si False, explique pourquoi (ex: 'Aucun chiffre n'a été fourni', 'La source est manquante').")

# --- 5. L'ÉDITEUR FINAL (Format simple pour l'IA) ---
class VeristralFinalOutput(BaseModel):
    fact_check: str | None = Field(description="Obligatoire si statistiques ou rhétorique. UNE SEULE PHRASE percutante avec le vrai chiffre ou l'esquive.")
    contexte: str | None = Field(description="Obligatoire si un événement est mentionné. MAXIMUM DEUX PHRASES de contexte neutre.")
    sources_utilisees: list[str] = Field(default_factory=list, description="Liste des noms de domaine (ex: ['insee.fr']).")

# =============================================================================
# 3. MOTEUR DE RECHERCHE & UTILS (VERSION PYRAMIDE & ROBUSTE)
# =============================================================================
import re

# On remet les stopwords ici pour la fonction _tokenize
FRENCH_STOPWORDS = {"alors", "avec", "avoir", "bien", "cette", "dans", "dont", "elle", "elles", "entre", "etre", "fait", "faire", "mais", "meme", "nous", "pour", "plus", "pas", "que", "qui", "sans", "sont", "sur", "tout", "tous", "tres", "une", "des", "les", "du", "de", "la", "le", "un", "est", "et", "ou", "en", "il", "ils", "on", "je", "tu", "vous"}

def _tokenize(text: str) -> list[str]:
    """Tokenize une phrase pour le cache ou l'analyse rapide."""
    return [t for t in re.findall(r"[a-zA-ZÀ-ÿ0-9]+", (text or "").lower()) if len(t) >= 3 and t not in FRENCH_STOPWORDS]

def _domain_to_organization(url: str) -> str:
    """Extrait le domaine principal pour un affichage propre dans OBS."""
    try: 
        return urlparse(url).netloc.lower().replace("www.", "")
    except: 
        return "source"

async def _search_and_sort_sources(query: str, allow_social: bool = False) -> list[dict]:
    """
    Recherche web via Mistral, extraction et tri pyramidal des sources.
    Filtre les réseaux sociaux sauf si 'allow_social' est True (utile pour l'historique d'un politicien).
    """
    # Sécurité : Si la requête est trop courte, on n'appelle pas Mistral
    if len(query) < 10: 
        return []
        
    try:
        res = await client.beta.conversations.start_async(
            model=_SMART_MODEL, 
            inputs=query, 
            tools=[{"type": "web_search"}]
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
                            
                            # On intègre la source si elle a un bon score, 
                            # OU si c'est un réseau social mais qu'on a expressément autorisé la recherche sociale
                            if score > 0 or (allow_social and score == -1):
                                # On donne un petit score arbitraire (5) aux RS autorisés pour qu'ils soient en bas de liste
                                final_score = score if score > 0 else 5 
                                candidates.append({"url": url, "organization": host, "score": final_score})
                                
        # Tri pyramidal par score décroissant (Gouv -> Médias -> Reste -> RS)
        candidates.sort(key=lambda x: x.get("score", 0), reverse=True)
        
        # On nettoie la clé 'score' pour correspondre au schéma Pydantic et on garde le top 3
        final_sources = [{"url": c["url"], "organization": c["organization"]} for c in candidates]
        return final_sources[:3] 
        
    except Exception as e:
        print(f"⚠️ Erreur de recherche web : {e}")
        return []
    
# =============================================================================
# 4. PROMPTS SIMPLIFIÉS & SPÉCIALISÉS (LOGIQUE MULTI-AGENTS)
# =============================================================================
import json

# --- 1. LE NETTOYEUR ---
def build_cleaner_prompt(affirmation: str) -> str:
    return f"""MISSION : Tu es un éditeur spécialisé dans la correction de transcriptions vocales (Speech-to-Text).
    Analyse cette phrase : '{affirmation}'
    
    RÈGLES STRICTES :
    1. CORRECTION PHONÉTIQUE : Corrige les mots absurdes (ex: "le cuit" -> "le QI", "s'en morts" -> "cent morts").
    2. NETTOYAGE : Extrais l'affirmation brute.
    3. ÉVÉNEMENT : Met 'contient_evenement' à True si c'est un fait historique/social/légal concret.
    4. VÉRIFIABILITÉ : C'est crucial. Si la phrase est une opinion subjective, une émotion, un vœu ou un superlatif abstrait non mesurable (ex: "notre plus grande richesse", "il fait beau", "je suis fier"), tu DOIS mettre 'est_verifiable' à False. Si c'est un fait ou un chiffre, met True.
    """

# --- 2. LE ROUTEUR (Le chef d'aiguillage) ---
def build_routeur_prompt(clean_text: str, texte_original: str) -> str:
    return f"""MISSION : Tu es le routeur d'un système de fact-checking.
    Phrase à analyser : '{clean_text}' (Originale : '{texte_original}')
    
    RÈGLES DE DÉCLENCHEMENT (Réponds par True ou False pour chaque. Sois très strict) :
    - run_stats : True SI ET SEULEMENT SI la phrase contient une quantité (chiffre, pourcentage, ou les mots "plus", "moins", "aucun", "beaucoup", "zéro", "tous").
    - run_contexte : True SI ET SEULEMENT SI la phrase mentionne un événement matériel (guerre, bombardement, événement social, vote d'une loi).
    - run_coherence_personnelle : True SI ET SEULEMENT SI l'orateur parle explicitement de LUI-MÊME, de son parti, et de la CONSTANCE DE SON AVIS (ex: "J'ai toujours dit que", "Nous avons toujours voté contre", "Je n'ai jamais changé d'avis"). INTERDIT de mettre True si la phrase est la simple affirmation d'un fait, d'une idée ou d'une statistique.
    - run_rhetorique : True SI ET SEULEMENT SI on te fournit la question du journaliste et que tu dois vérifier si le politicien y a répondu au lieu de noyer le poisson.
    """

# --- 3. LES EXPERTS (Le cœur de la présentation) ---
def build_stat_prompt(affirmation: str, sources_text: str) -> str:
    return f"""MISSION : Fact-checking STATISTIQUE.
    Affirmation : '{affirmation}'
    SOURCES FIABLES : {sources_text}
    
    RÈGLES ABSOLUES : 
    1. Évalue si le chiffre est VRAI, FAUX, ou TROMPEUR. 🚨 ATTENTION : Si le chiffre du politicien est une approximation raisonnable ou un arrondi proche de la réalité (ex: 65% au lieu de 64.8% ou "environ 65%"), le verdict DOIT IMPÉRATIVEMENT être 'VRAI'.
    2. Si l'affirmation est FAUSSE, tu DOIS chercher et écrire la VRAIE statistique actuelle dans 'chiffre_cle' (Ex: "330 000 SDF selon la Fondation Abbé Pierre"). Ne te contente pas de dire "aucune source ne confirme".
    3. Rédige 'analyse_detaillee' en 15 mots max.
    """

def build_contexte_prompt(affirmation: str, sources_text: str) -> str:
    return f"""MISSION : Fact-checking de CONTEXTE d'un événement.
    Affirmation : '{affirmation}'
    SOURCES FIABLES : {sources_text}
    
    RÈGLE : Rédige une explication factuelle. Si c'est une loi, résume le vote. Si c'est un conflit/événement, donne le contexte matériel. MAXIMUM 2 PHRASES.
    """

def build_coherence_prompt(affirmation: str, sources_text: str, personne: str) -> str:
    return f"""MISSION : Vérification de COHÉRENCE PERSONNELLE.
    La personne ({personne}) prétend avoir toujours tenu cette ligne : '{affirmation}'.
    SOURCES (Archives/Réseaux) : {sources_text}
    RÈGLE : Indique en une phrase si les archives confirment ou contredisent cette constance (ex: "Faux, il a voté contre en 2022.").
    """

def build_rhetorique_prompt(question_journaliste: str, reponse_politicien: str) -> str:
    return f"""MISSION : Analyse RHÉTORIQUE.
    Question posée : '{question_journaliste}'
    Réponse donnée : '{reponse_politicien}'
    RÈGLE : Indique en une phrase si le politicien répond directement à la question ou s'il utilise une technique d'esquive (whataboutism, changement de sujet).
    """

# --- 4. LE JUGE (La boucle de sécurité) ---
def build_judge_prompt(agent_type: str, reponse_agent: str) -> str:
    return f"""MISSION : Tu es l'évaluateur qualité.
    Agent évalué : '{agent_type}'
    Réponse : '{reponse_agent}'
    
    CRITÈRES DE VALIDATION :
    - Si l'agent est 'statistique' : La réponse DOIT contenir un chiffre.
    - Si l'agent est 'contexte' : La réponse DOIT parler d'un événement factuel.
    - Si l'agent est 'coherence' ou 'rhetorique' : La réponse est TOUJOURS valide (met 'est_valide' à True).
    
    Si c'est bon, met 'est_valide' à True. Sinon, False et explique pourquoi.
    """

# --- 5. L'ÉDITEUR FINAL (Pour l'affichage OBS) ---
def build_final_editor_prompt(rapports: list) -> str:
    return f"""MISSION : Tu es le rédacteur en chef TV. 
    Voici les rapports validés des experts : {json.dumps(rapports, ensure_ascii=False)}

    RÈGLES ABSOLUES DE FORMATAGE POUR LE DIRECT :
    1. 'fact_check' : Ce champ est réservé aux alertes en direct. 
       - Si tu as un rapport STATISTIQUE dont le verdict est 'FAUX' ou 'TROMPEUR', rédige UNE SEULE PHRASE (ex: "FAUX : L'INSEE dénombre...").
       - Si tu as un rapport RHÉTORIQUE indiquant que l'orateur esquive, ajoute : "ESQUIVE : L'orateur ne répond pas à la question posée."
       - Si tu as les DEUX, combine-les en une phrase courte.
       - 🚨 INTERDICTION ABSOLUE : Si la stat est 'VRAI' et qu'il n'y a pas d'esquive, laisse ce champ null.
    
    2. 'contexte' : Si tu as un rapport de contexte, rédige MAXIMUM DEUX PHRASES factuelles. Si aucun rapport de contexte, laisse null.
    3. 'sources_utilisees' : Liste uniquement les noms de domaine des sources citées dans les rapports affichés.
    """
# =============================================================================
# 5. POOL D'AGENTS & EXECUTION (AVEC BOUCLE DU JUGE)
# =============================================================================
from dataclasses import dataclass

@dataclass
class AgentPool:
    specialist_ids: dict[str, str]

_POOL_INSTANCE = None

async def init_agent_pool():
    global _POOL_INSTANCE
    print("⏳ Démarrage des agents Mistral (Création stricte JSON)...")
    ids = {}
    for key, defi in AGENT_DEFINITIONS.items():
        # Configuration stricte pour forcer le respect des schémas Pydantic
        fmt = {
            "type": "json_schema", 
            "json_schema": {"name": defi["schema"], "schema": defi["cls"].model_json_schema(), "strict": True}
        }
        res = await client.beta.agents.create_async(
            name=f"agent-veristral-{key}", 
            model=defi["model"], 
            completion_args={"temperature": 0.0, "response_format": fmt}
        )
        ids[key] = res.id
        print(f"✅ Agent '{key}' initialisé.")
        
    _POOL_INSTANCE = AgentPool(specialist_ids=ids)
    print("🚀 Tous les agents sont prêts !")

async def run_task(agent_key: str, prompt: str) -> dict:
    """Exécute une tâche simple (One-shot) avec un agent."""
    try:
        res = await client.beta.conversations.start_async(
            agent_id=_POOL_INSTANCE.specialist_ids[agent_key], 
            inputs=prompt
        )
        return json.loads(res.model_dump()["outputs"][-1]["content"])
    except Exception as e:
        print(f"⚠️ Erreur API pour l'agent {agent_key} : {e}")
        return {}

async def run_agent_with_judge(agent_key: str, initial_prompt: str, max_retries: int = 1) -> dict:
    prompt = initial_prompt
    
    for attempt in range(max_retries + 1):
        resultat = await run_task(agent_key, prompt)
        if not resultat:
            return {}

        # ⚡ 1. LE JUGE PYTHON (Instantané, pour les Stats)
        if agent_key == "statistique":
            texte_a_verifier = str(resultat.get("chiffre_cle", "")) + str(resultat.get("analyse_detaillee", ""))
            
            # Vérifie s'il y a un chiffre (0-9) ou un mot clé d'absence
            if any(char.isdigit() for char in texte_a_verifier) or "inconnu" in texte_a_verifier.lower():
                return resultat # ✅ Validation immédiate en 0.001s !
            else:
                raison = "Aucun chiffre détecté dans 'chiffre_cle' ou 'analyse_detaillee'."
                print(f"⚡ [JUGE PYTHON] Rejet 'statistique' ({attempt+1}/{max_retries+1}) ❌ {raison}")
                prompt = initial_prompt + f"\n\n🚨 CORRIGE IMMÉDIATEMENT : Tu dois ABSOLUMENT inclure un nombre (ex: 10, 20%, 300000)."
                continue

        # 🧠 2. LE JUGE LLM (Pour les contextes plus complexes)
        reponse_str = json.dumps(resultat, ensure_ascii=False)
        juge_prompt = build_judge_prompt(agent_key, reponse_str)
        jugement = await run_task("juge", juge_prompt)
        
        if jugement.get("est_valide", False):
            return resultat
        else:
            raison = jugement.get("raison_rejet", "Ne respecte pas les consignes.")
            print(f"⚖️ [JUGE LLM] Rejet '{agent_key}' ({attempt+1}/{max_retries+1}) ❌ {raison}")
            prompt = initial_prompt + f"\n\n🚨 LE JUGE A REJETÉ. Raison : {raison}. Corrige."
            
    print(f"⚠️ Limite d'essais atteinte pour '{agent_key}'. Passage en force.")
    return resultat

# --- DÉFINITION DES AGENTS ---
AGENT_DEFINITIONS = {
    "nettoyeur": {"model": _FAST_MODEL, "schema": "cleaner_output", "cls": CleanerOutput},
    "routeur": {"model": _FAST_MODEL, "schema": "routeur_output", "cls": RouteurOutput},
    "statistique": {"model": _SMART_MODEL, "schema": "statistique_output", "cls": StatistiqueOutput},
    "contexte": {"model": _SMART_MODEL, "schema": "contexte_output", "cls": ContexteOutput},
    "coherence": {"model": _SMART_MODEL, "schema": "coherence_output", "cls": CoherenceOutput},
    "rhetorique": {"model": _FAST_MODEL, "schema": "rhetorique_output", "cls": RhetoriqueOutput},
    "juge": {"model": _FAST_MODEL, "schema": "judge_output", "cls": JudgeOutput},
    "editeur_final": {"model": _BEST_MODEL, "schema": "veristral_final_output", "cls": VeristralFinalOutput},
}

# =============================================================================
# 6. ANALYSE (LA VERSION MULTI-AGENTS PARALLÉLISÉE)
# =============================================================================
import hashlib

@activity.defn
async def analyze_debate_line(data: dict) -> dict:
    # 0. CACHE DE SÉCURITÉ
    phrase_id = hashlib.md5(data['affirmation'].strip().lower().encode()).hexdigest()
    if phrase_id in CACHE_RESULTATS_GLOBAUX: 
        return CACHE_RESULTATS_GLOBAUX[phrase_id]

    print(f"\n🎬 DÉBUT ANALYSE : '{data['affirmation']}'")

    # 1. NETTOYEUR (Agent 1)
    prompt_cleaner = build_cleaner_prompt(data['affirmation'])
    nettoyage = await run_task("nettoyeur", prompt_cleaner)
    
    clean_text = nettoyage.get("phrase_nettoyee")
    contient_evenement = nettoyage.get("contient_evenement", False)
    est_verifiable = nettoyage.get("est_verifiable", True) # <--- AJOUT DU VIDEUR ICI
    
    # 🚨 FIX CRITIQUE : Si l'IA a "nettoyé" la phrase en chaîne vide, on force l'originale
    if not clean_text or len(clean_text) < 2:
        clean_text = data['affirmation']

    print(f"✨ TEXTE NETTOYÉ : '{clean_text}' (Événement : {contient_evenement} | Vérifiable : {est_verifiable})")

    # 2. ROUTEUR (Agent 2)
    texte_pour_routeur = clean_text
    if data.get('question'):
        texte_pour_routeur += f" (Suite à la question : {data['question']})"
        
    prompt_routeur = build_routeur_prompt(texte_pour_routeur, data['affirmation'])
    routage = await run_task("routeur", prompt_routeur)
    
    # 🔥 Forçage de l'agent Contexte si le Nettoyeur a vu un événement
    if contient_evenement:
        routage["run_contexte"] = True

    # 🛡️ FALLBACK STATS (Si l'IA rate le mot "aucun")
    stats_indicators = ["aucun", "plus aucun", "zéro", "0", "100", "tous", "%"]
    if not any([routage.get("run_stats"), routage.get("run_contexte"), routage.get("run_coherence_personnelle")]):
        if any(word in clean_text.lower() for word in stats_indicators):
            routage["run_stats"] = True

    # 🛑 1er GARDE-FOU : LE VIDEUR ANTI-OPINION (AJOUT ICI)
    if not est_verifiable:
        print("🛡️ [GARDE-FOU] Opinion ou phrase abstraite détectée. Annulation des vérifications factuelles.")
        routage["run_stats"] = False
        routage["run_contexte"] = False

    # 🛑 2ème GARDE-FOU : LE COUPE-CIRCUIT COHÉRENCE
    # On force 'coherence' à False si on n'a pas les mots clés stricts
    mots_constance = ["toujours", "jamais", "constance", "historiquement"]
    if not any(mot in clean_text.lower() for mot in mots_constance):
        routage["run_coherence_personnelle"] = False
        
    print(f"🔀 DÉCISION ROUTEUR FINALE : {routage}")

    # 3. EXPERTS & PARALLÉLISATION (Agents 3, 4, 5, 6 + Juge)
    tasks = []
    
    # Définition des sous-tâches asynchrones
    async def task_stat():
        srcs = await _search_and_sort_sources(f"statistiques officielles France {clean_text}")
        prompt = build_stat_prompt(clean_text, json.dumps(srcs, ensure_ascii=False))
        return await run_agent_with_judge("statistique", prompt)

    async def task_contexte():
        srcs = await _search_and_sort_sources(f"contexte factuel {clean_text}")
        prompt = build_contexte_prompt(clean_text, json.dumps(srcs, ensure_ascii=False))
        return await run_agent_with_judge("contexte", prompt)
        
    async def task_coherence():
        srcs = await _search_and_sort_sources(f"archives déclarations {data.get('personne', 'politicien')} {clean_text}", allow_social=True)
        prompt = build_coherence_prompt(clean_text, json.dumps(srcs, ensure_ascii=False), data.get('personne', 'politicien'))
        return await run_agent_with_judge("coherence", prompt)

    async def task_rhetorique():
        # Pas de recherche web ici ! On compare directement.
        question = data.get('question', '')
        prompt = build_rhetorique_prompt(question, data['affirmation'])
        return await run_agent_with_judge("rhetorique", prompt)

    # Ajout des tâches selon la décision du Routeur
    if routage.get("run_stats"): tasks.append(task_stat())
    if routage.get("run_contexte"): tasks.append(task_contexte())
    if routage.get("run_coherence_personnelle"): tasks.append(task_coherence())
    # On lance la rhétorique SI le routeur le demande ET qu'une question a bien été posée
    if routage.get("run_rhetorique") and data.get("question"): tasks.append(task_rhetorique())
    
    # Exécution simultanée de toutes les tâches requises
    rapports = await asyncio.gather(*tasks) if tasks else []
    
    # Nettoyage des éventuels retours vides
    rapports = [r for r in rapports if r] 
    
    # 🧹 Filtrage Python de sécurité : On supprime les rapports statistiques "VRAI" 
    # pour interdire formellement à l'Éditeur d'afficher un bandeau quand l'orateur a raison.
    rapports = [r for r in rapports if not (r.get("agent") == "statistique" and r.get("verdict", "").upper() == "VRAI")]

    # 4. ÉDITION FINALE (Agent 8)
    if rapports:
        prompt_editeur = build_final_editor_prompt(rapports)
        final = await run_task("editeur_final", prompt_editeur)
        
        # 🛡️ LE TUEUR D'HALLUCINATIONS (La Censure Python)
        # Si le routeur n'a PAS demandé de contexte, on écrase sans pitié 
        # ce que l'Éditeur final a essayé d'inventer.
        if not routage.get("run_contexte"):
            final["contexte"] = None
            
        # Pareil pour le fact-check stat/rhétorique : on nettoie s'ils n'étaient pas appelés
        if not routage.get("run_stats") and not routage.get("run_rhetorique"):
            final["fact_check"] = None
            
    else:
        # Si aucun expert n'a été déclenché
        final = {"fact_check": None, "contexte": None, "sources_utilisees": []}

    # 5. MAPPING AU FORMAT OBS EXACT
    # On construit la réponse finale dans le format imbriqué attendu par le logiciel de régie
    
    texte_claim = clean_text
    summary_parts = []
    
    if final.get("fact_check"):
        summary_parts.append(final["fact_check"])
    if final.get("contexte"):
        summary_parts.append(final["contexte"])
        
    summary_complet = " ".join(summary_parts) if summary_parts else None

    # Déduction du verdict global
    verdict_obs = None
    if final.get("fact_check"):
        if "FAUX" in final["fact_check"].upper(): verdict_obs = "inaccurate"
        elif "TROMPEUR" in final["fact_check"].upper(): verdict_obs = "partially_accurate"
    
    # Création des sources au bon format
    sources_obs = [{"organization": org, "url": ""} for org in final.get("sources_utilisees", [])]

    # Le dictionnaire final qui part vers OBS
    obs_output = {
        "claim": {"text": texte_claim},
        "analysis": {
            "summary": summary_complet,
            "sources": sources_obs
        },
        "overall_verdict": verdict_obs,
        "afficher_bandeau": bool(summary_complet)
    }
    
    CACHE_RESULTATS_GLOBAUX[phrase_id] = obs_output
    return obs_output

