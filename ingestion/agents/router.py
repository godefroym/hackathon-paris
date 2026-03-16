#!/usr/bin/env python3
"""
router.py — MinitralRouter
==========================
Classifie une affirmation en entrée dans l'une des 3 catégories
utilisées par le pipeline Veristral :

  STATISTIC      → chiffre, statistique, pourcentage, indicateur économique
  POLICY_STANCE  → prise de position sur une politique (vote, opinion tranchée)
  TOPIC_MENTION  → simple mention d'un sujet lié aux intérêts d'un élu

Scoring pondéré :
  - Stance forte (« je suis contre », « retraite ») → 2.0 par match
  - Stance faible (« nous devons », « il faut »)    → 0.5 par match
  - Statistique                                     → 1.0 par match
  - Topic HATVP (« santé », « clinique »)           → 1.0 par match

La catégorie avec le score pondéré le plus élevé est retournée.
Un score minimum de 0.6 est requis pour éviter de router les phrases
contenant uniquement des expressions faibles (« nous devons »).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Category(str, Enum):
    """Catégories de routage pour le pipeline Veristral."""

    STATISTIC = "STATISTIC"
    POLICY_STANCE = "POLICY_STANCE"
    TOPIC_MENTION = "TOPIC_MENTION"
    UNKNOWN = "UNKNOWN"


@dataclass
class RouteResult:
    """Résultat de la classification par ``MinitralRouter``.

    Attributes
    ----------
    category:
        Catégorie détectée parmi `Category`.
    confidence:
        Score indicatif entre 0.0 et 1.0.
    matched_keywords:
        Liste des mots-clés ayant déclenché la classification.
    raw_text:
        Texte original soumis au routeur.
    """

    category: Category
    confidence: float
    matched_keywords: list[str]
    raw_text: str


# ---------------------------------------------------------------------------
# Heuristiques par mots-clés
# ---------------------------------------------------------------------------

_STATISTIC_PATTERNS: list[str] = [
    r"\b\d+[\.,]?\d*\s*%",
    r"\b\d+\s*(milliards?|millions?|milliers?|euros?|dollars?)",
    r"\btaux\b",
    r"\bindice\b",
    r"\bchômage\b",
    r"\bPIB\b",
    r"\bcroissance\b",
    r"\bstatistique\b",
    r"\bchiffre\b",
    r"\brecord\b",
    r"\bhausse\b",
    r"\bbaisse\b",
    r"\baugmentation\b",
    r"\bdiminution\b",
    r"\bemplois?\b",
]

# Fort signal individuel → poids 2.0 chacun
_POLICY_STANCE_STRONG_PATTERNS: list[str] = [
    r"\bje suis (contre|pour|favorable|oppos[eé]|d[eé]favorable)\b",
    r"\bj[e']ai vot[eé]\b",
    r"\bj[e']ai toujours (soutenu|d[eé]fendu|combattu|refus[eé])\b",
    r"\bma position\b",
    r"\bmon engagement\b",
    r"\bje m[e']engage\b",
    r"\bje refuse\b",
    r"\bje soutiens\b",
    r"\bje combats\b",
    r"\btotalement (favorable|oppos[eé]|contre|pour)\b",
    r"\bferme(ment)? oppos[eé]\b",
    r"\bje ne veux pas\b",
    r"\bje veux\b",
    r"\bje propose\b",
    r"\bretraites?\b",
    r"\b\d{2} ans\b",  # Pour "62 ans", "65 ans"
]

# Signal générique → poids 0.5 chacun (ne doit pas écraser un topic fort)
_POLICY_STANCE_WEAK_PATTERNS: list[str] = [
    r"\bnous devons\b",
    r"\bil faut (absolument|imp[eé]rativement)?\b",
]

_TOPIC_MENTION_PATTERNS: list[str] = [
    r"\b[eé]nergie\b",
    r"\bp[eé]trole\b",
    r"\bgaz\b",
    r"\bcarburant\b",
    r"\bTotalEnergy\b",
    r"\beau\b",
    r"\bhydraulique\b",
    r"\bAquaFrance\b",
    r"\bfinance\b",
    r"\bbourse\b",
    r"\bactionnaire\b",
    r"\binvestissement\b",
    r"\bsecteur\b",
    r"\bindustrie\b",
    r"\bsant[eé]\b",
    r"\bcliniques?\b",
    r"\bpriv[eé]es?\b",
    r"\bSant[eé]Plus\b",
]


def _scan(text: str, patterns: list[str], weight: float) -> tuple[float, list[str]]:
    """Calcule le score pondéré et la liste des mots-clés matchés."""
    score = 0.0
    keywords: list[str] = []
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            score += weight
            keywords.append(m.group(0).strip())
    return score, keywords


class MinitralRouter:
    """Routeur léger (heuristiques, zéro appel API) pour le pipeline Veristral.

    - SCORE_MIN_THRESHOLD = 0.6 : évite de router les « nous devons » isolés.
    """

    SCORE_MIN_THRESHOLD = 0.6

    def route(self, text: str) -> RouteResult:
        """Classifie ``text`` et retourne un ``RouteResult``."""
        lowered = text.lower()

        stat_score, stat_kw = _scan(lowered, _STATISTIC_PATTERNS, 1.0)
        strong_score, strong_kw = _scan(lowered, _POLICY_STANCE_STRONG_PATTERNS, 2.0)
        weak_score, weak_kw = _scan(lowered, _POLICY_STANCE_WEAK_PATTERNS, 0.5)
        topic_score, topic_kw = _scan(lowered, _TOPIC_MENTION_PATTERNS, 1.0)

        stance_score = strong_score + weak_score
        stance_kw = strong_kw + weak_kw

        total = stat_score + stance_score + topic_score
        if total == 0.0:
            return RouteResult(
                category=Category.UNKNOWN,
                confidence=0.0,
                matched_keywords=[],
                raw_text=text,
            )

        scores: dict[Category, tuple[float, list[str]]] = {
            Category.STATISTIC: (stat_score, stat_kw),
            Category.POLICY_STANCE: (stance_score, stance_kw),
            Category.TOPIC_MENTION: (topic_score, topic_kw),
        }

        # On ne garde que les catégories dépassant le seuil
        valid_scores = {
            cat: val for cat, val in scores.items() if val[0] >= self.SCORE_MIN_THRESHOLD
        }

        if not valid_scores:
            return RouteResult(
                category=Category.UNKNOWN,
                confidence=0.0,
                matched_keywords=[],
                raw_text=text,
            )

        best = max(valid_scores, key=lambda c: valid_scores[c][0])
        best_score, best_kw = valid_scores[best]

        return RouteResult(
            category=best,
            confidence=float(round(best_score / total, 2)),
            matched_keywords=best_kw,
            raw_text=text,
        )
