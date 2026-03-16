#!/usr/bin/env python3
"""
conflict_of_interest_agent.py — ConflictOfInterestAgent
========================================================
Agent HATVP : détecte un potentiel conflit d'intérêts.
Charge dynamiquement les données en fonction du politicien configuré.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ConflictResult:
    """Résultat d'analyse du ``ConflictOfInterestAgent``."""
    has_conflict: bool
    politician: str
    sector: str = ""
    company: str = ""
    alert_message: str = ""
    matched_keywords: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)


class ConflictOfInterestAgent:
    """Détecte les conflits d'intérêts basés sur le nom du politicien."""

    def __init__(self, hatvp_path: str | Path | None = None) -> None:
        self._root_dir = Path(__file__).resolve().parent.parent.parent
        self._data: dict = {}
        self._politician_name = "Inconnu"
        
        # Tentative de lecture de session_config.json
        self._config = self._load_session_config()
        self._politician_name = self._config.get("politician_name", "Inconnu")

        if hatvp_path:
            self._hatvp_path = Path(hatvp_path)
        else:
            # Recherche dynamique du fichier : {firstname}_{lastname}_hatvp.json
            safe_name = self._politician_name.lower().replace(" ", "_")
            self._hatvp_path = self._root_dir / "demo_data" / f"{safe_name}_hatvp.json"
            
            # Fallback si absent
            if not self._hatvp_path.exists():
                self._hatvp_path = self._root_dir / "demo_data" / "hatvp_mock.json"

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
        """Charge et valide les données HATVP."""
        if not self._hatvp_path.exists():
            # Si aucun fichier spécifié n'existe, on retourne un dict vide
            return {}
        try:
            with self._hatvp_path.open(encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {}

    def analyze(self, text: str) -> ConflictResult:
        """Analyse le texte pour détecter des conflits."""
        lowered = text.lower()
        
        # On utilise le nom du config ou celui dans le JSON
        politician_display = self._data.get("nom", self._politician_name)

        # On cherche dans "mandats_prives"
        for mandat in self._data.get("mandats_prives", []):
            secteur = mandat.get("secteur", "")
            entreprise = mandat.get("entreprise", "")
            
            # Mots-clés basés sur le secteur et l'entreprise (on peut en déduire d'autres)
            keywords = [entreprise, "secteur", "groupe"]
            if secteur:
                # On splitte les mots du secteur pour avoir plus de matches
                keywords.extend(secteur.replace("/", " ").replace("-", " ").split())
            
            # Nettoyage des mots courts
            keywords = [kw for kw in keywords if len(kw) > 3]
            
            matched = [kw for kw in keywords if kw.lower() in lowered]
            if matched:
                remun = mandat.get("remuneration_annuelle", "N/A")
                role = mandat.get("fonction", "Membre")
                source_url = mandat.get("source_url", "")
                
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
                    sector=secteur,
                    company=entreprise,
                    alert_message=alert,
                    matched_keywords=matched,
                    details=mandat,
                )

        return ConflictResult(has_conflict=False, politician=politician_display)
