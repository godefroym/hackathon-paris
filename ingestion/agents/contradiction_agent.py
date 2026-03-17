#!/usr/bin/env python3
"""
contradiction_agent.py — ContradictionAgent
============================================
Agent "Flip-Flop" : détecte les contradictions.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ContradictionResult:
    """Résultat d'analyse du ``ContradictionAgent``."""
    has_contradiction: bool
    politician: str
    topic: str = ""
    past_date: str = ""
    past_quote: str = ""
    alert_message: str = ""
    matched_keywords: list[str] = field(default_factory=list)
    past_source: str = ""


class ContradictionAgent:
    """Détecte les retournements de position avec filtrage temporel."""

    def __init__(self, archives_path: str | Path | None = None) -> None:
        self._root_dir = Path(__file__).resolve().parent.parent.parent
        self._data: list = []
        
        # Lecture session_config.json
        self._config = self._load_session_config()
        self._politician_name = self._config.get("politician_name", "Marc Valmont")
        self._video_year = self._config.get("video_year", 2026)

        if archives_path:
            self._archives_path = Path(archives_path)
        else:
            safe_name = self._politician_name.lower().replace(" ", "_").replace("é", "e")
            self._archives_path = self._root_dir / "demo_data" / f"{safe_name}_archives.json"
            if not self._archives_path.exists():
                self._archives_path = self._root_dir / "demo_data" / "archives_mock.json"

        self._data = self._load_data()

    def _load_session_config(self) -> dict:
        config_path = self._root_dir / "session_config.json"
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _load_data(self) -> list:
        if not self._archives_path.exists():
            return []
        try:
            with self._archives_path.open(encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, dict) and "archives" in data:
                    return data["archives"]
                return data if isinstance(data, list) else []
        except Exception:
            return []

    def analyze(self, text: str) -> ContradictionResult:
        lowered = text.lower()
        politician_display = self._politician_name

        for archive in self._data:
            # Filtrage par année
            archive_date = archive.get("date", "1900-01-01")
            try:
                archive_year = int(archive_date.split("-")[0])
            except (ValueError, IndexError):
                archive_year = 1900
            
            if archive_year > self._video_year:
                continue

            sujet = archive.get("sujet", archive.get("topic", ""))
            
            # Mots-clés étendus pour la démo
            keywords = [
                sujet.lower(), 
                "retraite", 
                "49.3",
                "taxe carbone", 
                "nucléaire", 
                "éolien",
                "62 ans", 
                "65 ans",
                "64 ans"
            ]
            
            matched = [kw for kw in keywords if kw and kw in lowered]
            if matched:
                past_date = archive.get("date", "inconnue")
                past_quote = archive.get("declaration_officielle", archive.get("quote", ""))
                source_url = archive.get("source_url", "")

                alert = (
                    f"🔄 Contradiction détectée ({sujet}).\n"
                    f"   ↳ {politician_display} déclarait le {past_date} : \"{past_quote}\"\n"
                    f"   ↳ Position actuelle semble en contradiction."
                )
                if source_url:
                    alert += f" [🔍 Vérifier la source]({source_url})"

                return ContradictionResult(
                    has_contradiction=True,
                    politician=politician_display,
                    topic=sujet,
                    past_date=past_date,
                    past_quote=past_quote,
                    alert_message=alert,
                    matched_keywords=matched,
                    past_source=f"Archives ({past_date})"
                )

        return ContradictionResult(has_contradiction=False, politician=politician_display)
