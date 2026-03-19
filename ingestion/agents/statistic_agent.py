"""
StatisticAgent — Veristral Expert
================================
Agent spécialisé dans la validation de données statistiques pour la démo.
Identifie le sujet de la statistique et renvoie une source vérifiée et vivante.
"""
from dataclasses import dataclass

@dataclass
class StatisticResult:
    is_valid: bool
    source_name: str
    source_url: str
    message: str

class StatisticAgent:
    def __init__(self):
        # Mapping de sujets vers des sources réelles vérifiées
        self.sources = {
            "pouvoir d'achat": {
                "name": "INSEE",
                "url": "https://www.insee.fr/fr/statistiques/8212176",
                "msg": "L'INSEE indique que le pouvoir d'achat du revenu disponible brut des ménages a progressé de 2,6 % en 2024."
            },
            "électricité": {
                "name": "RTE France",
                "url": "https://www.rte-france.com/actualites/bilan-electrique-2024-annee-records-transition-france",
                "msg": "RTE confirme qu'en 2024, la France a atteint un solde exportateur record de 89 TWh, loin d'être importatrice nette."
            }
        }

    def analyze(self, claim: str) -> StatisticResult:
        claim_lower = claim.lower()
        
        # Sujets spécifiques pour Élise Beaumont
        if "pouvoir d'achat" in claim_lower:
            s = self.sources["pouvoir d'achat"]
            return StatisticResult(True, s["name"], s["url"], s["msg"])
        
        if "électricité" in claim_lower or "électrique" in claim_lower:
            s = self.sources["électricité"]
            return StatisticResult(True, s["name"], s["url"], s["msg"])
            
        # Fallback générique
        return StatisticResult(
            False, 
            "Insee", 
            "https://www.insee.fr/fr/accueil", 
            "Statistique non spécifiée dans la base de démo."
        )
