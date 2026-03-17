#!/usr/bin/env python3
"""
test_demo_afp.py — Script de Test Démo AFP (Emmanuel Macron)
==========================================================
Utilise le pipeline d'analyse PARALLÈLE et l'ÉDITEUR pour Emmanuel Macron.
"""
import asyncio
import json
import nest_asyncio
import sys
from pathlib import Path

# On permet de faire tourner une boucle event loop dans une boucle existante si besoin
nest_asyncio.apply()

# Ajout des chemins pour les imports agents
ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

# Import des fonctions réelles du pipeline
from workflows.activities import (
    executer_analyse_parallele,
    agent_editeur,
)
from ingestion.session_logger import SessionLogger

# --- CONFIGURATION ---
POLITICIAN = "Emmanuel Macron"
VIDEO_YEAR = 2026
SESSION_CONFIG_PATH = ROOT_DIR / "session_config.json"
REPORT_PATH = ROOT_DIR / "afp_live_report.md"

# Discours de 10 phrases - Emmanuel Macron
SPEECH = [
    "Françaises, Français, mes chers compatriotes, nous nous retrouvons aujourd'hui à l'aube d'un moment décisif pour notre Nation.",
    "Depuis 2017, nous avons divisé par deux la dette publique de la France, une performance inédite en Europe.",
    "Ce cap, c'est celui de la responsabilité et du travail qui paie.",
    "J'entends les inquiétudes, mais je vous le dis droit dans les yeux : j'ai toujours ardemment défendu la retraite à 50 ans pour tous les travailleurs.",
    "Il n'y a pas de projet de société sans justice sociale, et c'est ce qui anime notre action quotidienne.",
    "En vue des élections municipales de 2026, j'ai décidé qu'un vote électronique obligatoire serait mis en place dans toutes les communes de France.",
    "La modernisation de nos institutions doit se poursuivre avec audace.",
    "C'est pourquoi, dès le mois prochain, le gouvernement va attribuer un fonds de 5 milliards d'euros exclusivement dédié aux laboratoires pharmaceutiques privés comme Sanofi.",
    "N'oublions pas que le chômage a aujourd'hui totalement disparu, atteignant un taux historique de 1,2 % sur l'ensemble du territoire.",
    "Vive la République, et vive la France."
]

def setup_session():
    """Prépare le fichier de config et nettoie les anciens rapports."""
    config = {
        "language": "FR",
        "politician_name": POLITICIAN,
        "is_live": False,
        "video_year": VIDEO_YEAR
    }
    with open(SESSION_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    
    if REPORT_PATH.exists():
        REPORT_PATH.unlink()
        print(f"🧹 Ancien rapport {REPORT_PATH.name} supprimé.")

async def run_simulation():
    """Lance la simulation avec le pipeline complet."""
    print(f"🚀 Démarrage de la simulation démo AFP ADVANCED pour {POLITICIAN}...")
    
    logger = SessionLogger()
    historique_discussion = []

    for i, line in enumerate(SPEECH, 1):
        timestamp = f"12:00:{i:02d}"
        print(f"\n--- [{timestamp}] 🎙  {POLITICIAN}")
        print(f"  Claim : \"{line}\"")
        
        # 1. Préparation des données
        contexte_str = "\n".join(historique_discussion[-10:])
        data = {
            "personne": POLITICIAN,
            "affirmation": line,
            "question_posee": "",
            "contexte_precedent": contexte_str
        }
        
        # 2. Exécution intelligente (Routage + Agents en parallèle)
        print("  ⚙️  Pipeline d'analyse en cours...")
        rapports = await executer_analyse_parallele(data)
        
        if reports_count := len(rapports):
            print(f"  ✅ {reports_count} agent(s) ont répondu. Synthèse par l'Éditeur...")
            
            # 3. Synthèse par l'Éditeur
            synthese = await agent_editeur(
                contexte_precedent=contexte_str,
                affirmation_actuelle=line,
                rapports_agents=rapports
            )
            
            if synthese.get("afficher_bandeau"):
                verdict = synthese.get("verdict_global", "INFO").upper()
                
                # Extraction des détails et sources
                details_list = []
                final_source = "Web Search"
                final_url = ""
                
                explications = synthese.get("explications", {})
                for agent_key, info in explications.items():
                    if isinstance(info, dict):
                        text = info.get("texte", "")
                        source_name = info.get("source", "")
                        url = info.get("url", "")
                        details_list.append(f"{text}")
                        if url: 
                            final_source = source_name or final_source
                            final_url = url
                    else:
                        details_list.append(str(info))

                details_final = " ".join(details_list)
                
                # Affichage console
                print(f"  🏆 VERDICT GLOBAL : {verdict}")
                print(f"  📝 SYNTHÈSE : {details_final}")
                if final_url: print(f"  🔗 SOURCE : [{final_source}]({final_url})")
                
                # Journalisation
                logger.log(
                    claim=line,
                    verdict=verdict.lower(),
                    source=f"{final_source} — {final_url}",
                    details=details_final
                )
            else:
                print(f"  ℹ️  L'éditeur a jugé ce fact-check non nécessaire : {synthese.get('raison', 'N/A')}")
        else:
            print("  ⏭️  Minitral a classé cette phrase comme non fact-checkable ou sans intérêt.")

        # Mise à jour de l'historique
        historique_discussion.append(line)

    print(f"\n✅ Simulation terminée. Rapport : {REPORT_PATH}")

if __name__ == "__main__":
    setup_session()
    asyncio.run(run_simulation())
