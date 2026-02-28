import os
import json
import asyncio 
from pathlib import Path
import requests
from temporalio import activity
from mistralai import Mistral
from tavily import TavilyClient
from dotenv import load_dotenv

# --- ASTUCE POUR LE CHEMIN DES CLÉS ---
# On récupère le chemin du dossier 'workflows'
current_dir = Path(__file__).parent
# On remonte d'un cran pour atteindre la racine où se trouve 'cle.env'
env_path = current_dir.parent / "cle.env"

# On charge le fichier spécifiquement
load_dotenv(dotenv_path=env_path)

# Vérification (optionnelle pour débugger)
if not os.getenv("TAVILY_API_KEY"):
    print(f"❌ Erreur : Impossible de trouver les clés dans {env_path}")
else:
    print(f"✅ Clés chargées depuis {env_path}")

# Initialisation des clients
client = Mistral(api_key=os.getenv("MISTRAL_API_KEY"))
tavily_client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

SOCIAL_BLACKLIST = ["tiktok.com", "facebook.com", "instagram.com", "x.com", "twitter.com"]
DEFAULT_FACT_CHECK_POST_URL = "http://localhost:8000/api/stream/fact-check"

# --- AGENT 1 : STATISTIQUES (MODE INVESTIGATION LIBRE) ---
async def agent_statistique(data):
    print(f"📊 [Agent Stat] Investigation approfondie en cours...")
    
    query_complete = f"{data['affirmation']} chiffres officiels France 2025 2026 (site:gouv.fr OR site:insee.fr OR site:vie-publique.fr OR site:lemonde.fr OR site:afp.com OR site:lefigaro.fr)"

    try:
        search = tavily_client.search(
            query=query_complete, 
            search_depth="basic", 
            max_results=3, 
            exclude_domains=SOCIAL_BLACKLIST
        )
        sources = "\n".join([f"Source: {r['url']}\nContenu: {r['content']}" for r in search.get('results', [])])
    except: 
        sources = "Aucune source fiable."

    prompt = f"""Vérifie cette affirmation : '{data['affirmation']}'. Sources trouvées : {sources}.
    RÈGLES STRICTES :
    1. verdict : "vrai", "faux", "exagéré", "trompeur" (sois précis sur la nuance).
    2. analyse_detaillee : Fais une analyse détaillée (environ 5 à 7 phrases). Décortique le chiffre, donne le vrai chiffre, ajoute de la nuance si la méthode de calcul du politicien est biaisée.
    3. nom_source : Le nom de la PREMIÈRE source uniquement.
    4. url_source : L'URL de la première source.
    
    JSON: {{"agent": "statistique", "verdict": "vrai|faux|...", "analyse_detaillee": "...", "nom_source": "...", "url_source": "..."}}"""
    
    res = await client.chat.complete_async(
        model="mistral-small-latest", 
        messages=[{"role": "user", "content": prompt}], 
        response_format={"type": "json_object"}
    )
    return json.loads(res.choices[0].message.content)

# --- AGENT 2 : RHÉTORIQUE ---
async def agent_rhetorique(data):
    print(f"🧠 [Agent Rhétorique] Analyse logique...")
    prompt = f"""Analyse : Question posée : '{data.get('question_posee', '')}' | Réponse : '{data.get('affirmation', '')}'
    RÈGLES STRICTES :
    1. Si la personne répond à la question (ou s'il n'y avait pas de question) : Laisse "explication" VIDE "".
    2. Si la personne esquive : Explique en une phrase qu'elle ne répond pas à la question posée.
    
    JSON: {{"agent": "rhetorique", "explication": "..."}}"""
    
    res = await client.chat.complete_async(model="mistral-small-latest", messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"})
    return json.loads(res.choices[0].message.content)

# --- AGENT 3 : COHÉRENCE PERSONNELLE ---
async def agent_coherence_personnelle(data):
    print(f"🕵️ [Agent Cohérence] Accès réseaux sociaux pour {data['personne']}...")
    try:
        search = tavily_client.search(
            query=f"déclaration {data['personne']} {data['affirmation']} 2025 2026", search_depth="advanced", max_results=3
        )
        sources = "\n".join([f"Source: {r['url']}\nContenu: {r['content']}" for r in search.get('results', [])])
    except: sources = "Aucune archive."

    prompt = f"""Vérifie si {data['personne']} se contredit sur : '{data['affirmation']}'. Sources : {sources}.
    RÈGLES STRICTES :
    1. Si la personne est cohérente : Laisse "explication" VIDE "".
    2. Si incohérente : Cite brièvement les propos incohérents.
    
    JSON: {{"agent": "coherence", "explication": "..."}}"""
    
    res = await client.chat.complete_async(model="mistral-small-latest", messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"})
    return json.loads(res.choices[0].message.content)

# --- AGENT 4 : CONTEXTE (MODE INVESTIGATION LIBRE) ---
async def agent_contexte(data):
    print(f"📚 [Agent Contexte] Analyse factuelle détaillée...")
    
    query_complete = f"{data['affirmation']} contexte faits historiques France 2025 2026"

    try:
        search = tavily_client.search(
            query=query_complete, 
            search_depth="basic", 
            max_results=3, 
            exclude_domains=SOCIAL_BLACKLIST
        )
        sources = "\n".join([f"Source: {r['url']}\nContenu: {r['content']}" for r in search.get('results', [])])
    except: 
        sources = "Aucun contexte."

    prompt = f"""Analyse le contexte de : '{data['affirmation']}'. Sources : {sources}.
    ⚠️ ATTENTION CRITIQUE : Cette affirmation peut être un MENSONGE TOTAL. Ne la prends pas pour une vérité absolue.
    
    RÈGLES STRICTES :
    1. analyse_detaillee : Fais une analyse approfondie (environ 5 à 7 phrases) pour expliquer le contexte RÉEL. Si les sources contredisent l'affirmation, explique la vraie situation.
    2. nom_source : Nom de la source principale trouvée.
    3. url_source : L'URL de cette source.
    
    JSON: {{"agent": "contexte", "analyse_detaillee": "...", "nom_source": "...", "url_source": "..."}}"""
    
    res = await client.chat.complete_async(
        model="mistral-small-latest", 
        messages=[{"role": "user", "content": prompt}], 
        response_format={"type": "json_object"}
    )
    return json.loads(res.choices[0].message.content)

# --- ROUTEUR (CORRIGÉ POUR DÉTECTER LES MOTS QUANTITATIFS) ---
async def agent_routeur(data):
    prompt = f"""Tu es le cerveau analytique d'un système de fact-checking en direct.
    ENTRÉE BRUTE : '{data.get('affirmation', '')}'

    MISSION 1 : NETTOYAGE ET SYNTHÈSE
    Le texte peut contenir plusieurs phrases, des hésitations, ou des auto-corrections.
    - Garde uniquement l'intention finale corrigée.
    - Résume en UNE "affirmation_propre" claire et directe.

    MISSION 2 : ROUTAGE (RÈGLES ULTRA STRICTES)
    Sur la base de cette "affirmation_propre", active les experts (true/false) :
    - 'run_stats' : TRUE pour les chiffres, pourcentages, budgets, économie, OU les affirmations quantitatives absolues (ex: "aucun", "plus de", "tout le monde", "zéro").
    - 'run_rhetorique' : TRUE si une question a été posée ou si le discours esquive.
    - 'run_coherence_personnelle' : TRUE si la personne parle de son passé ou de ses propres déclarations.
    - 'run_contexte' : TRUE pour des évènements précis (JO, manifestations, lois) ou de grandes affirmations factuelles vérifiables (ex: "La France est le pays qui taxe le plus"). NE PAS ACTIVER pour des données purement chiffrées.

    Renvoie UNIQUEMENT un JSON strict :
    {{
      "affirmation_propre": "La phrase nettoyée",
      "run_stats": bool,
      "run_rhetorique": bool,
      "run_coherence_personnelle": bool,
      "run_contexte": bool
    }}
    """
    
    res = await client.chat.complete_async(
        model="mistral-small-latest", 
        messages=[{"role": "user", "content": prompt}], 
        response_format={"type": "json_object"}
    )
    return json.loads(res.choices[0].message.content)

# --- EXÉCUTEUR PARALLÈLE ---
async def executer_analyse_parallele(data):
    print(f"🚦 ENTRÉE BRUTE : '{data['affirmation'][:60]}...'")
    
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
    
    FORMAT JSON STRICT ATTENDU :
    {{
      "afficher_bandeau": true,
      "verdict_global": "Trompeur", // ou Vrai, Faux, À nuancer...
      "explications": {{
         "statistique": {{
            "texte": "Les 2 phrases de synthèse max.",
            "source": "Nom de la source"
         }},
         "contexte": {{
            "texte": "Les 2 phrases de synthèse max.",
            "source": "Nom de la source"
         }},
         "rhetorique": "Explication courte si esquive",
         "coherence": "Explication courte si contradiction"
      }}
    }}
    NOTE : N'inclus dans 'explications' que les clés des agents qui ont fourni une analyse utile.
    """
    
    res = await client.chat.complete_async(
        model="mistral-small-latest", 
        messages=[{"role": "user", "content": prompt}], 
        response_format={"type": "json_object"}
    )
    return json.loads(res.choices[0].message.content)

@activity.defn
async def analyze_debate_line(current_json: dict, last_minute_json: dict) -> dict:
    """
    Activité principale appelée par Temporal pour chaque phrase détectée.
    """
    # 1. Extraction des données du format de ton collègue
    personne = current_json.get("personne", "Intervenant inconnu")
    question = current_json.get("question_posee", "")
    affirmation = current_json.get("affirmation", "")
    
    # On fusionne les phrases des 60 dernières secondes pour le contexte
    phrases_contexte = last_minute_json.get("phrases", [])
    contexte_precedent = " ".join(phrases_contexte)

    # 2. Préparation du dictionnaire pour tes agents
    data_pour_agents = {
        "personne": personne,
        "question_posee": question,
        "affirmation": affirmation
    }

    print(f"🎤 Analyse en cours pour {personne}...")

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
        
        return resultat_final

    except Exception as e:
        print(f"❌ Erreur lors de l'analyse : {e}")
        return {
            "afficher_bandeau": False,
            "erreur": str(e)
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
        response = await asyncio.to_thread(_do_post)
        body_preview = response.text[:1000]
        return {
            "posted": response.ok,
            "status_code": response.status_code,
            "url": url,
            "response_body_preview": body_preview,
        }
    except Exception as exc:
        return {
            "posted": False,
            "url": url,
            "error": str(exc),
        }
