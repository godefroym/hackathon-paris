from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Political context profile — swap this object to adapt the whole pipeline
# to a different country or political system.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PoliticalProfile:
    """Describes the political & media landscape the agents operate in.

    Create one instance per country/context and pass it to all prompt builders.
    """

    country: str
    """Full country name (e.g. "France")."""

    language: str
    """Primary language for agent output (e.g. "French")."""

    event_type: str
    """Short label for the live event (e.g. "débat politique télévisé")."""

    institutional_sources: list[str] = field(default_factory=list)
    """Preferred official/institutional data sources for fact-checking."""

    trusted_media: list[str] = field(default_factory=list)
    """Reliable national/regional media outlets agents should favour."""

    key_institutions: list[str] = field(default_factory=list)
    """Government, parliament, courts and key bodies agents should know."""

    political_context_hint: str = ""
    """Free-form paragraph injected into every prompt to ground the agent
    in the current political landscape (elections, reforms, etc.)."""

    correction_markers: list[str] = field(default_factory=list)
    """Language-specific phrases that signal a speaker self-correction."""


# ── Built-in profile: France ──────────────────────────────────────────────

FRANCE_PROFILE = PoliticalProfile(
    country="France",
    language="French",
    event_type="débat politique télévisé français",
    institutional_sources=[
        "INSEE (Institut national de la statistique et des études économiques)",
        "Eurostat",
        "Cour des comptes",
        "Banque de France",
        "DARES (Direction de l'animation de la recherche, des études et des statistiques)",
        "DREES (Direction de la recherche, des études, de l'évaluation et des statistiques)",
        "Vie-publique.fr",
        "Légifrance",
        "Assemblée nationale / Sénat (comptes rendus)",
    ],
    trusted_media=[
        "Le Monde",
        "Libération",
        "Le Figaro",
        "France Info",
        "France Inter",
        "AFP",
        "Les Échos",
        "La Croix",
        "Mediapart",
        "Public Sénat",
        "LCP",
    ],
    key_institutions=[
        "Présidence de la République",
        "Premier ministre / Matignon",
        "Assemblée nationale",
        "Sénat",
        "Conseil constitutionnel",
        "Conseil d'État",
        "Cour des comptes",
        "Haut Conseil des finances publiques",
    ],
    political_context_hint=(
        "This is a live French political debate broadcast on national television. "
        "Speakers are typically French politicians, ministers, or candidates. "
        "Claims often reference French legislation, government programs (e.g. RSA, "
        "APL, Sécurité sociale), national budgets, and EU-level statistics. "
        "When searching, prioritise .gouv.fr, .fr, and EU domains. "
        "French political discourse frequently uses approximate or rounded figures; "
        "flag exaggeration rather than labelling small rounding as 'false'."
    ),
    correction_markers=[
        "pardon",
        "je corrige",
        "je me corrige",
        "je me suis trompé",
        "je me suis trompée",
        "plutôt",
        "rectification",
        "en fait",
        "non",
        "je voulais dire",
        "erratum",
    ],
)

# The active profile used by all prompt builders.
# Override at import time or via set_political_profile() for another country.
_active_profile: PoliticalProfile = FRANCE_PROFILE


def set_political_profile(profile: PoliticalProfile) -> None:
    """Replace the active political profile used by all prompt builders."""
    global _active_profile
    _active_profile = profile


def get_political_profile() -> PoliticalProfile:
    """Return the currently active political profile."""
    return _active_profile


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _source_guidance(profile: PoliticalProfile) -> str:
    """Build the source-preference paragraph injected into search-capable agents."""
    parts = [
        f"POLITICAL CONTEXT: {profile.political_context_hint}" if profile.political_context_hint else "",
        f"COUNTRY: {profile.country}.",
        f"EVENT TYPE: {profile.event_type}.",
        f"PREFERRED INSTITUTIONAL SOURCES: {', '.join(profile.institutional_sources)}."
        if profile.institutional_sources
        else "",
        f"TRUSTED MEDIA: {', '.join(profile.trusted_media)}."
        if profile.trusted_media
        else "",
        f"KEY INSTITUTIONS TO KNOW: {', '.join(profile.key_institutions)}."
        if profile.key_institutions
        else "",
    ]
    return "\n".join(p for p in parts if p)


def _lang_rule(profile: PoliticalProfile) -> str:
    return f"Always respond in {profile.language}, matching the language of the debate."


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------


def build_routeur_prompt(data: dict[str, Any]) -> str:
    profile = _active_profile
    return f"""You are the routing agent of a live fact-checking system for a {profile.event_type}.

{_source_guidance(profile)}

CURRENT SENTENCE TO EVALUATE (ONLY ONE SENTENCE):
'{data.get("affirmation", "")}'

PREVIOUS CONTEXT (FOR INFORMATION ONLY, NEVER FACT-CHECK THIS PART):
'{data.get("contexte_precedent", "")}'

STRICT RULES:
1. Fact-check ONLY the current sentence.
2. Never merge multiple sentences.
3. Previous context is only for detecting correction/retraction/redundancy.
4. If current sentence corrects/cancels a previous sentence, set all run_* to false.
5. `affirmation_propre` must be a concise reformulation of the current sentence only.
6. {_lang_rule(profile)}

Routing:
- run_stats: TRUE for numbers, percentages, budgets, economics, or quantitative claims.
- run_rhetorique: TRUE when a question exists and the current sentence evades it.
- run_coherence_personnelle: TRUE when statement consistency of the person is relevant.
- run_contexte: TRUE for verifiable events/laws/context, but not pure numeric claims already covered by stats.

Return ONLY this strict JSON:
{{
  "affirmation_propre": "Reformulated current sentence",
  "run_stats": bool,
  "run_rhetorique": bool,
  "run_coherence_personnelle": bool,
  "run_contexte": bool
}}
"""


def build_stat_prompt(data: dict[str, Any]) -> str:
    profile = _active_profile
    return f"""Verify this numeric/statistical claim made during a {profile.event_type}:
CLAIM: '{data['affirmation']}'
QUESTION ASKED: '{data.get('question_posee', '')}'

{_source_guidance(profile)}

<workflow>
## 1. Search (MANDATORY — never skip)
Call web_search with at least one targeted query combining the key figures, policy keywords, and
"{profile.country}" to retrieve local results. If results are inconclusive or sources are weak,
refine the query and search again (e.g. add the date, the law name, or the institution name).

## 2. Analyse
Review each search result. Collect the most recent official figures from institutional sources.
Note any discrepancy between the claim and the real data, including magnitude and direction.

## 3. Write output
Produce the structured JSON below.
- verdict: "vrai", "faux", "exagéré", or "trompeur".
- analyse_detaillee: 5 to 7 concise, precise sentences grounded in what you found.
- sources: list of {{"url": "https://...", "organization": "Name"}} — populate with the ACTUAL
  HTTP URLs returned by your web_search calls. Include up to 3 of the most relevant ones.
  This field is the ONLY way source links reach the broadcast — do NOT leave it empty if you
  found sources.
- {_lang_rule(profile)}
</workflow>
"""


def build_rhetorique_prompt(data: dict[str, Any]) -> str:
    profile = _active_profile
    return f"""Analyze rhetorical evasion in a {profile.event_type}.
Question: '{data.get('question_posee', '')}' | Answer: '{data.get('affirmation', '')}'

{_source_guidance(profile)}

STRICT RULES:
1. If the person answers the question (or if there is no question), keep "explication" EMPTY "".
2. If the person evades, explain in one sentence that they do not answer the asked question.
3. Political rhetoric is common; only flag clear evasion, not just partial answers.
4. {_lang_rule(profile)}

Expected JSON:
{{"agent": "rhetorique", "explication": "..."}}
"""


def build_coherence_prompt(data: dict[str, Any]) -> str:
    profile = _active_profile
    return f"""Check whether {data['personne']} contradicts themselves about this claim made during a {profile.event_type}:
CLAIM: '{data['affirmation']}'
QUESTION ASKED: '{data.get('question_posee', '')}'

{_source_guidance(profile)}

<workflow>
## 1. Search (MANDATORY — never skip)
Call web_search with at least one query combining "{data['personne']}", the claim topic, and
relevant policy keywords to look for past public statements. If results are inconclusive,
try alternative queries (e.g. different dates, bill names, or paraphrased positions).

## 2. Analyse
Compare each prior statement found against the current claim. Note date, context, and whether
the difference represents a genuine contradiction or a legitimate evolution of position.

## 3. Write output
Produce the structured JSON below.
- If coherent or no prior statements found: leave "explication" empty.
- If incoherent: one or two sentences citing the contradiction and, when available, its date.
- sources: list of {{"url": "https://...", "organization": "Name"}} — populate with the ACTUAL
  HTTP URLs returned by your web_search calls. Include up to 3 of the most relevant ones.
  This field is the ONLY way source links reach the broadcast — do NOT leave it empty if you
  found sources.
- {_lang_rule(profile)}
</workflow>
"""


def build_contexte_prompt(data: dict[str, Any]) -> str:
    profile = _active_profile
    return f"""Provide factual background context for a claim made during a {profile.event_type}:
CLAIM: '{data['affirmation']}'
QUESTION ASKED: '{data.get('question_posee', '')}'

CRITICAL WARNING: this claim may be entirely false — search without assuming its validity.

{_source_guidance(profile)}

<workflow>
## 1. Search (MANDATORY — never skip)
Call web_search with at least one query combining the claim keywords and "{profile.country}" to
retrieve local institutional and media results. If results are insufficient, refine and search
again (e.g. add specific dates, law names, or institution names).

## 2. Analyse
Survey all results. Extract the real factual landscape: what is confirmed, what is exaggerated,
what is missing, and what surrounding context the viewer needs to understand the claim.

## 3. Write output
Produce the structured JSON below.
- analyse_detaillee: 5 to 7 factual sentences explaining the real context.
- sources: list of {{"url": "https://...", "organization": "Name"}} — populate with the ACTUAL
  HTTP URLs returned by your web_search calls. Include up to 3 of the most relevant ones.
  This field is the ONLY way source links reach the broadcast — do NOT leave it empty if you
  found sources.
- {_lang_rule(profile)}
</workflow>
"""


def build_editor_prompt(
    *,
    contexte_precedent: str,
    affirmation_actuelle: str,
    rapports_agents: list[dict[str, Any]],
) -> str:
    profile = _active_profile
    return f"""You are the Editor-in-Chief of a live {profile.event_type} broadcast in {profile.country}.

{_source_guidance(profile)}

1. CONVERSATION HISTORY (previous 10 sentences):
"{contexte_precedent}"

2. CLAIM TO FACT-CHECK (current moment):
"{affirmation_actuelle}"

3. DETAILED SPECIALIST AGENT REPORTS (full raw text — read every word):
{json.dumps(rapports_agents, ensure_ascii=False)}

NOTE ON SOURCES: each specialist report may contain a "sources" list with actual HTTP URLs
the agent found during web search. When writing explications, pick the most relevant source
from the corresponding specialist report and copy its url and organization into the explication
field. Do NOT invent or hallucinate URLs — only use URLs that appear in the specialist reports.

<workflow>
## 1. Read all reports
Read every specialist report in full. Note what each agent found, where they agree, where they
contradict, and whether any key dimension is missing or weak.

## 2. Assess overall truthfulness
Weigh the combined evidence: statistical accuracy, rhetorical evasion, personal incoherence, and
factual context. Apply {profile.country}-specific norms — minor rounding in political speeches
should yield 'Exagéré', not 'Faux'. Check the conversation history for redundancy or prior
corrections — if the claim was already addressed or the speaker self-corrected, note it in `raison`.

## 3. Write output
Produce the final JSON verdict. Compress the synthesis into exactly two concise, impactful,
TV-ready sentences when writing `texte` fields. Include only `explications` keys that add genuine
value — omit empty or redundant ones.
</workflow>

STRICT JSON FORMAT:
{{
  "verdict_global": "Trompeur",
  "raison": "optional short reason if redundant or skipped",
  "explications": {{
     "statistique": {{"texte": "...", "source": "INSEE", "url": ""}},
     "contexte": {{"texte": "...", "source": "Le Monde", "url": ""}},
     "rhetorique": "...",
     "coherence": {{"texte": "...", "source": "France Info", "url": ""}}
  }}
}}

Include only useful keys in `explications`.
- {_lang_rule(profile)}
"""


def build_self_correction_prompt(
    *,
    current_affirmation: str,
    next_affirmation: str,
    contexte_precedent: str,
) -> str:
    profile = _active_profile
    return f"""You are a live correction detector for a {profile.event_type}.

CURRENT_SENTENCE:
"{current_affirmation}"

NEXT_SENTENCE:
"{next_affirmation}"

PREVIOUS_CONTEXT:
"{contexte_precedent}"

Task:
- Determine whether NEXT_SENTENCE explicitly corrects/retracts CURRENT_SENTENCE.
- Correction examples in {profile.language}: {', '.join(f'"{m}"' for m in profile.correction_markers) if profile.correction_markers else '"I correct myself", "I was wrong", replacement number'}.
- If NEXT_SENTENCE is only an addition/new idea/rephrase, it is NOT a correction.
- {_lang_rule(profile)}

Return ONLY strict JSON:
{{
  "next_is_correction": true|false,
  "confidence": 0.0,
  "reason": "short"
}}
"""

def build_claim_extraction_prompt(
    *,
    sentences: list[str],
    personne: str,
    question_posee: str,
) -> str:
    """Build the prompt for the claim-extractor agent.

    The agent receives a short transcript window (~20 seconds of speech, typically
    4-10 sentences) and must return ONLY concrete, verifiable factual claims.
    It must be highly selective: 0-2 claims per window is normal.
    """
    profile = _active_profile
    numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(sentences))
    return f"""You are a live fact-checking claim extractor for a {profile.event_type} in {profile.country}.

SPEAKER: {personne or "Unknown"}
QUESTION BEING DISCUSSED: {question_posee or "(none)"}

TRANSCRIPT WINDOW (~20 seconds of speech):
{numbered}

{_source_guidance(profile)}

YOUR TASK — SELECTIVE EXTRACTION:
Extract ONLY concrete, verifiable factual claims. Be extremely selective.

INCLUDE:
✅ Precise statistics or figures (e.g. "le chômage est à 5 %", "nous avons créé 200 000 emplois")
✅ Specific historical or legal facts ("la loi X a été votée en 2022")
✅ Budget or financial claims ("le déficit est de 6 % du PIB")
✅ Causal attributions with measurable claims ("grâce à notre politique, la croissance a doublé")

EXCLUDE:
❌ Political opinions, promises, intentions ("je veux", "nous allons", "il faut")
❌ General rhetoric or values ("la France est forte", "nous sommes engagés")
❌ Questions, interjections, or filler phrases
❌ Self-corrections or retractions already made in the same window
❌ Claims that are too vague to verify ("les choses vont mieux")
❌ Paraphrases of what another person said without a specific checkable fact

For EACH extracted claim:
- affirmation: the clean, verbatim or lightly reformulated checkable claim
- contexte: 1-2 sentences of surrounding speech for context
- personne: the speaker's name
- question_posee: the question being discussed (empty if none)
- type_claim: one of "statistique", "historique", "juridique", "budgetaire", "attribution", "autre"

If the window contains NO checkable facts, return an empty claims list.

Return ONLY strict JSON:
{{
  "claims": [
    {{
      "affirmation": "...",
      "contexte": "...",
      "personne": "{personne or ""}",
      "question_posee": "{question_posee or ""}",
      "type_claim": "statistique"
    }}
  ]
}}
- {_lang_rule(profile)}
"""
