#!/usr/bin/env python3
"""
test_demo_afp.py
================
Script de simulation pour la démo AFP Veristral.
Valide le routage et la journalisation pour 5 phrases clés.
"""

import os
import sys
import json
from pathlib import Path

# Configuration du path pour les imports
sys.path.insert(0, str(Path(__file__).resolve().parent / "ingestion"))

from agents.router import MinitralRouter, Category
from agents.conflict_of_interest_agent import ConflictOfInterestAgent
from agents.contradiction_agent import ContradictionAgent
from session_logger import SessionLogger

def run_demo_test():
    print("🚀 Démarrage de la simulation démo AFP Veristral...")
    
    # Reset du rapport AFP pour le test
    report_path = Path("afp_live_report.md")
    if report_path.exists():
        report_path.unlink()
        print("🧹 Ancien rapport afp_live_report.md supprimé.")

    # Initialisation des composants
    router = MinitralRouter()
    conflict_agent = ConflictOfInterestAgent()
    contradiction_agent = ContradictionAgent()
    logger = SessionLogger(report_path=report_path)

    sentences = [
        {
            "id": 1,
            "text": "Mes chers compatriotes, notre pays traverse une crise économique sans précédent et nous devons nous rassembler.",
            "expected_category": Category.UNKNOWN
        },
        {
            "id": 2,
            "text": "Aujourd'hui, le taux de chômage des jeunes a explosé et atteint les 35 % dans notre pays, c'est un record absolu !",
            "expected_category": Category.STATISTIC
        },
        {
            "id": 3,
            "text": "C'est pour cela que je l'annonce ce soir avec fermeté : je suis le seul candidat à proposer de repousser l'âge de départ à la retraite à 65 ans pour sauver notre système.",
            "expected_category": Category.POLICY_STANCE
        },
        {
            "id": 4,
            "text": "Il faut du courage politique pour prendre ces décisions difficiles.",
            "expected_category": Category.UNKNOWN
        },
        {
            "id": 5,
            "text": "Et pour financer notre santé, nous devons massivement subventionner le secteur des cliniques privées, qui sont les seules à pouvoir absorber le choc actuel.",
            "expected_category": Category.TOPIC_MENTION
        }
    ]

    processed_count = 0
    logged_count = 0

    print("\n" + "─" * 50)
    for s in sentences:
        text = s["text"]
        expected = s["expected_category"]
        
        print(f"处理 [Phrase {s['id']}] : \"{text[:60]}...\"")
        
        route = router.route(text)
        print(f"  Resultat Routage : {route.category.value} (Attendu: {expected.value})")
        
        # Assertion du routage
        assert route.category == expected, f"Erreur de routage pour phrase {s['id']}"

        # Simulation du pipeline (dispatching)
        if route.category != Category.UNKNOWN:
            verdict = "Unknown"
            source = ""
            details = ""

            if route.category == Category.STATISTIC:
                verdict = "Unknown"
                source = "Stats — Web Search / RAG (Simulation)"
            elif route.category == Category.POLICY_STANCE:
                res = contradiction_agent.analyze(text)
                if res.has_contradiction:
                    verdict = "Contradiction"
                    source = f"Archives — {res.topic}"
                    details = res.alert_message
                    print(f"    🔄 {res.alert_message}")
            elif route.category == Category.TOPIC_MENTION:
                res = conflict_agent.analyze(text)
                if res.has_conflict:
                    verdict = "Conflict"
                    source = f"HATVP — {res.company}"
                    details = res.alert_message
                    print(f"    ⚠️ {res.alert_message}")

            # Journalisation
            logger.log(claim=text, verdict=verdict, source=source, details=details)
            logged_count += 1
            print(f"    ✅ Journalisé dans afp_live_report.md")
        else:
            print(f"    ⏩ Ignoré (UNKNOWN)")

        processed_count += 1
        print("─" * 50)

    # Validation finale du fichier
    print(f"\n📊 Validation finale...")
    assert logged_count == 3, f"Attendu 3 entrées journalisées, obtenu {logged_count}"
    
    if report_path.exists():
        content = report_path.read_text()
        entries = [line for line in content.splitlines() if line.startswith("| **[")]
        print(f"  Entrées réelles dans le fichier : {len(entries)}")
        assert len(entries) == 3, f"Le fichier contient {len(entries)} lignes de claim au lieu de 3"
    
    print("\n✨ Simulation démo AFP réussie ! Tous les tests passent.")

if __name__ == "__main__":
    try:
        run_demo_test()
    except AssertionError as e:
        print(f"\n❌ ECHEC : {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 ERREUR CRITIQUE : {e}")
        sys.exit(1)
