#!/usr/bin/env python3
"""
conflict_of_interest_agent.py — ConflictOfInterestAgent
==========================================================
Agent "HATVP" : détecte les conflits d'intérêts.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ConflictResult:
    """Résultat d'analyse du ``ConflictOfInterestAgent``."""
    has_conflict: bool
    politician: str
    company: str = ""
    sector: str = ""
    alert_message: str = ""


class ConflictOfInterestAgent:
    """Analyse les claims pour détecter des liens d'intérêts financiers."""

    def __init__(self, data_path: str | Path | None = None) -> None:
        self._root_dir = Path(__file__).resolve().parent.parent.parent
        self._data: dict = {}

        # Lecture session_config.json
        self._config = self._load_session_config()
        self._politician_name = self._config.get("politician_name", "Marc Valmont")

        if data_path:
            self._data_path = Path(data_path)
        else:
            safe_name = self._politician_name.lower().replace(" ", "_").replace("é", "e")
            self._data_path = self._root_dir / "demo_data" / f"{safe_name}_hatvp.json"
            if not self._data_path.exists():
                self._data_path = self._root_dir / "demo_data" / "hatvp_mock.json"

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

    def _load_data(self) -> dict:
        if not self._data_path.exists():
            return {}
        try:
            with self._data_path.open(encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {}

    def analyze(self, text: str) -> ConflictResult:
        lowered = text.lower()
        politician_display = self._data.get("nom", self._politician_name)
        mandats = self._data.get("mandats_prives", [])

        for mandat in mandats:
            entreprise = mandat.get("entreprise", "")
            secteur = mandat.get("secteur", "")
            
            # Mots-clés sectoriels ou nom d'entreprise
            keywords = [entreprise.lower(), secteur.lower(), "[ée]olien", "offshore", "santé", "clinique"]
            
            import re
            matched = any(re.search(kw, lowered) for kw in keywords if kw)
            
            if matched:
                remun = mandat.get("remuneration_annuelle", "N/A")
                role = mandat.get("fonction", "Membre")
                source_url = mandat.get("source_url", self._data.get("source_url", ""))
                
                alert = (
                    f"⚠️ Alerte HATVP : {politician_display} est {role} chez "
                    f"{entreprise} ({secteur}). Rémunération : {remun}. "
                    f"Conflit d'intérêts potentiel détecté."
                )
                if source_url:
                    alert += f" [🔍 Vérifier la source]({source_url})"
                    
                return ConflictResult(
                    has_conflict=True,
                    politician=politician_display,
                    company=entreprise,
                    sector=secteur,
                    alert_message=alert,
                )

        return ConflictResult(has_conflict=False, politician=politician_display)
