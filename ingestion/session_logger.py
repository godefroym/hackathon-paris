#!/usr/bin/env python3
"""
session_logger.py — SessionLogger
===================================
Journalise chaque claim traité par le pipeline Veristral dans un fichier
Markdown ``afp_live_report.md`` formaté pour export AFP.

Format de chaque entrée
-----------------------
::

    **[HH:MM:SS]** | **Claim:** "..." | **Verdict:** [True/False/Contradiction/Conflict] | **Source/Details:** ...

Le fichier est créé automatiquement s'il n'existe pas.
Un en-tête de session est inséré à la première écriture.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

# Valeurs autorisées pour le champ Verdict
VERDICT_TRUE = "True"
VERDICT_FALSE = "False"
VERDICT_CONTRADICTION = "Contradiction"
VERDICT_CONFLICT = "Conflict"
VERDICT_UNKNOWN = "Unknown"


class SessionLogger:
    """Journalise les claims fact-checkés dans un rapport Markdown AFP.

    Parameters
    ----------
    report_path:
        Chemin du fichier Markdown de sortie (créé s'il n'existe pas).
        Par défaut : ``afp_live_report.md`` à la racine du projet.
    timezone_offset:
        Fuseau horaire pour les horodatages affichés (``None`` = UTC).

    Example
    -------
    >>> logger = SessionLogger()
    >>> logger.log(
    ...     claim="Le chômage a baissé de 3%.",
    ...     verdict=VERDICT_TRUE,
    ...     source="INSEE, T4 2023",
    ... )
    """

    def __init__(
        self,
        report_path: str | Path | None = None,
        timezone_offset: int | None = None,
    ) -> None:
        if report_path is None:
            report_path = (
                Path(__file__).resolve().parent.parent / "afp_live_report.md"
            )
        self._report_path = Path(report_path)
        self._timezone_offset = timezone_offset
        self._session_started = False

    # ------------------------------------------------------------------
    # Écriture
    # ------------------------------------------------------------------

    def _now_str(self) -> str:
        """Renvoie l'heure courante au format HH:MM:SS (heure locale)."""
        return datetime.now().strftime("%H:%M:%S")

    def _write_session_header(self) -> None:
        """Insère un en-tête de session dans le rapport."""
        now = datetime.now()
        header = (
            f"\n\n---\n\n"
            f"## Session — {now.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"| Horodatage | Claim | Verdict | Source / Détails |\n"
            f"|:---:|:---|:---:|:---|\n"
        )
        with self._report_path.open("a", encoding="utf-8") as fh:
            fh.write(header)
        self._session_started = True

    def log(
        self,
        claim: str,
        verdict: str,
        source: str = "",
        details: str = "",
    ) -> None:
        """Ajoute une ligne dans le rapport Markdown AFP.

        Parameters
        ----------
        claim:
            Texte de l'affirmation transcrite (citation exacte).
        verdict:
            Verdict parmi ``VERDICT_TRUE``, ``VERDICT_FALSE``,
            ``VERDICT_CONTRADICTION``, ``VERDICT_CONFLICT``, ``VERDICT_UNKNOWN``.
        source:
            Source ou référence (ex. "INSEE Q4 2023", "Archives JO 2022-10-14").
        details:
            Détails complémentaires (ex. message d'alerte, citation contradictoire).
        """
        if not self._session_started:
            self._write_session_header()

        timestamp = self._now_str()
        source_details = source
        if details:
            source_details = f"{source} — {details}" if source else details

        # Nettoyage des caractères pipe (risque de casser le tableau Markdown)
        safe_claim = claim.replace("|", "\\|")
        safe_source = source_details.replace("|", "\\|").replace("\n", " ")

        # Icône selon verdict
        verdict_icon = {
            VERDICT_TRUE: "✅ True",
            VERDICT_FALSE: "❌ False",
            VERDICT_CONTRADICTION: "🔄 Contradiction",
            VERDICT_CONFLICT: "⚠️ Conflict",
            VERDICT_UNKNOWN: "❓ Unknown",
        }.get(verdict, verdict)

        line = (
            f"| **[{timestamp}]** "
            f"| **Claim :** \"{safe_claim}\" "
            f"| {verdict_icon} "
            f"| {safe_source} |\n"
        )

        with self._report_path.open("a", encoding="utf-8") as fh:
            fh.write(line)

    def log_raw(self, entry: str) -> None:
        """Écrit une ligne brute dans le rapport (pour métadonnées libres).

        Parameters
        ----------
        entry:
            Contenu brut à ajouter (Markdown libre).
        """
        if not self._session_started:
            self._write_session_header()
        with self._report_path.open("a", encoding="utf-8") as fh:
            fh.write(entry + "\n")
