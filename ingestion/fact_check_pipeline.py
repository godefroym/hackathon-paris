#!/usr/bin/env python3
"""
fact_check_pipeline.py — Orchestrateur Veristral
=================================================
Ce script s'intercale en aval de ``realtime_transcript.py``  via un pipe Unix.
Il lit des lignes JSONL sur stdin, route chaque affirmation vers l'agent
approprié, et journalise les résultats dans ``afp_live_report.md``.

Usage (production)
------------------
::

    python realtime_transcript.py --personne "Jean-Pierre Valentin" ... \\
        | python fact_check_pipeline.py

Usage (démo — sans micro)
--------------------------
::

    echo '<json_line>' | python fact_check_pipeline.py --demo

Format JSON attendu en entrée (JSONL)
--------------------------------------
::

    {
        "personne": "Jean-Pierre Valentin",
        "affirmation_courante": "Je suis contre la taxe carbone.",
        "affirmation": "...",
        "metadata": {"timestamp": "2026-03-16T12:00:00Z", ...}
    }

Contraintes
-----------
- N'importe PAS ``realtime_transcript.py`` ; pas de modification du code OBS.
- Modulaire : chaque agent est dans son propre module.
- Sûr : les erreurs d'un agent n'interrompent pas le pipeline.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ajoute le répertoire courant au path pour les imports relatifs
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agents.conflict_of_interest_agent import (
    ConflictOfInterestAgent,
    ConflictResult,
)
from agents.contradiction_agent import ContradictionAgent, ContradictionResult
from agents.router import Category, MinitralRouter
from agents.statistic_agent import StatisticAgent, StatisticResult
from session_logger import (
    VERDICT_CONFLICT,
    VERDICT_CONTRADICTION,
    VERDICT_UNKNOWN,
    SessionLogger,
)

# ---------------------------------------------------------------------------
# Couleurs ANSI pour le terminal
# ---------------------------------------------------------------------------
_RESET = "\033[0m"
_BOLD = "\033[1m"
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_RED = "\033[91m"
_CYAN = "\033[96m"
_MAGENTA = "\033[95m"


def _color(text: str, color: str) -> str:
    return f"{color}{text}{_RESET}"


# ---------------------------------------------------------------------------
# Traitement d'un claim
# ---------------------------------------------------------------------------

def process_claim(
    claim: str,
    personne: str,
    timestamp: str,
    router: MinitralRouter,
    conflict_agent: ConflictOfInterestAgent,
    contradiction_agent: ContradictionAgent,
    statistic_agent: StatisticAgent,
    logger: SessionLogger,
    demo_mode: bool = False,
) -> None:
    """Route ``claim`` vers l'agent approprié, affiche le résultat et le journalise.

    Parameters
    ----------
    claim:
        Phrase transcrite à analyser.
    personne:
        Nom de l'intervenant (champ JSON ``personne``).
    timestamp:
        Horodatage ISO de la transcription.
    router:
        Instance de ``MinitralRouter``.
    conflict_agent:
        Instance de ``ConflictOfInterestAgent``.
    contradiction_agent:
        Instance de ``ContradictionAgent``.
    logger:
        Instance de ``SessionLogger``.
    demo_mode:
        Si ``True``, affiche un bandeau de mode démo.
    """
    print()
    print(_color("─" * 70, _CYAN))
    print(_color(f"[{timestamp}] 🎙  {personne}", _BOLD))
    print(f'  Claim : "{claim}"')

    route = router.route(claim)
    print(f"  Routage → {_color(route.category.value, _MAGENTA)} "
          f"(mots-clés : {route.matched_keywords})")

    verdict = VERDICT_UNKNOWN
    source = ""
    details = ""

    # ------------------------------------------------------------------
    if route.category == Category.TOPIC_MENTION:
        result: ConflictResult = conflict_agent.analyze(claim)
        if result.has_conflict:
            verdict = VERDICT_CONFLICT
            source = f"HATVP — {result.company} ({result.sector})"
            details = result.alert_message
            print(_color(f"  {result.alert_message}", _YELLOW))
        else:
            verdict = VERDICT_UNKNOWN
            source = "HATVP — aucun conflit détecté"
            print(_color("  ✓ Aucun conflit d'intérêts détecté.", _GREEN))

    # ------------------------------------------------------------------
    elif route.category == Category.POLICY_STANCE:
        result2: ContradictionResult = contradiction_agent.analyze(claim)
        if result2.has_contradiction:
            verdict = VERDICT_CONTRADICTION
            source = f"Archives — {result2.past_source}"
            details = result2.alert_message
            print(_color(f"  {result2.alert_message}", _RED))
        else:
            verdict = VERDICT_UNKNOWN
            source = "Archives — aucune contradiction détectée"
            print(_color("  ✓ Aucune contradiction détectée dans les archives.", _GREEN))

    # ------------------------------------------------------------------
    elif route.category == Category.STATISTIC:
        result3: StatisticResult = statistic_agent.analyze(claim)
        verdict = VERDICT_UNKNOWN
        source = f"{result3.source_name} (Simulation)"
        details = f"{result3.message} [🔍 Vérifier la source]({result3.source_url})"
        print(_color(
            "  📊 Statistique détectée → agent Web Search / RAG (simulé en mode démo).",
            _CYAN,
        ))
        print(_color(f"  {details}", _CYAN))

    # ------------------------------------------------------------------
    else:
        print(_color("  ❓ Aucune catégorie reconnue — ignoré.", _YELLOW))
        return  # Ne rien ajouter au rapport si ignoré

    logger.log(claim=claim, verdict=verdict, source=source, details=details)


# ---------------------------------------------------------------------------
# Boucle principale (stdin JSONL)
# ---------------------------------------------------------------------------

def run(demo_mode: bool = False) -> int:
    """Lit les lignes JSONL depuis stdin et orchestre le fact-checking.

    Parameters
    ----------
    demo_mode:
        Si ``True``, affiche un message de mode démo au démarrage.

    Returns
    -------
    int
        Code de retour (0 = succès).
    """
    router = MinitralRouter()
    conflict_agent = ConflictOfInterestAgent()
    contradiction_agent = ContradictionAgent()
    statistic_agent = StatisticAgent()
    logger = SessionLogger()

    # Lecture de la config de session
    config = {}
    config_path = Path(__file__).resolve().parent.parent / "session_config.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

    if demo_mode or config:
        print(_color("🚀 Session Veristral Initialisée", _BOLD))
        if config:
            print(f"   Langue : {config.get('language', 'FR')}")
            print(f"   Politicien : {config.get('politician_name', 'Inconnu')}")
            print(f"   Filtre Année : {config.get('video_year', 'N/A')}")
            print(f"   Mode : {'LIVE' if config.get('is_live') else 'VIDEO'}")
        print(_color("   En attente de transcription (stdin)…", _CYAN))

    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue

        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            print(f"[warn] Ligne JSON invalide ignorée : {exc}", file=sys.stderr)
            continue

        claim: str = payload.get("affirmation_courante", "").strip()
        if not claim:
            continue

        personne: str = payload.get("personne", "Inconnu")
        metadata: dict = payload.get("metadata", {})
        timestamp: str = metadata.get("timestamp", metadata.get("timestamp_elapsed", "?"))

        try:
            process_claim(
                claim=claim,
                personne=personne,
                timestamp=timestamp,
                router=router,
                conflict_agent=conflict_agent,
                contradiction_agent=contradiction_agent,
                statistic_agent=statistic_agent,
                logger=logger,
                demo_mode=demo_mode,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[error] Erreur lors du traitement du claim : {exc}", file=sys.stderr)

    print()
    print(_color("✅ Pipeline terminé. Rapport AFP :", _GREEN),
          str(logger._report_path))
    return 0


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Parse les arguments de la ligne de commande."""
    parser = argparse.ArgumentParser(
        description=(
            "Orchestrateur Veristral — lit des lignes JSONL depuis stdin "
            "et route chaque affirmation vers l'agent approprié."
        )
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Active le mode démo (affichage enrichi, pas d'appel réseau).",
    )
    return parser.parse_args()


def main() -> int:
    """Point d'entrée principal."""
    args = parse_args()
    try:
        return run(demo_mode=args.demo)
    except KeyboardInterrupt:
        print("\nArret demande (Ctrl+C).", file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())
