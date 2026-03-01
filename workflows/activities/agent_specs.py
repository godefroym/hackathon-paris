from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from .schemas import (
    ClaimExtractionOutput,
    CoherenceOutput,
    ContexteOutput,
    EditorOutput,
    RhetoriqueOutput,
    RouteurOutput,
    SelfCorrectionOutput,
    StatistiqueOutput,
)

# ── Per-agent default models ──────────────────────────────────────────────────
# These can all be overridden at runtime via environment variables
# (e.g. MISTRAL_MODEL_EDITEUR=mistral-large-latest).
#
# Decision rationale:
#   - "fast" tier  (ministral-8b-latest): extraction, routing, rhetoric, correction
#     → low-latency tasks where being first matters more than being right
#   - "smart" tier (mistral-medium-latest): search-grounded specialists
#     → grounded web-search analysis; medium cost/accuracy trade-off
#   - "best" tier  (mistral-large-latest): final synthesis (editor)
#     → the verdict seen on live TV; accuracy is paramount
_FAST_MODEL = "ministral-8b-latest"
_SMART_MODEL = "mistral-medium-latest"
_BEST_MODEL = "mistral-large-latest"


def response_format_for_model(schema_name: str, model_cls: type[BaseModel]) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": schema_name,
            "schema": model_cls.model_json_schema(),
            "strict": True,
        },
    }


AGENT_DEFINITIONS: dict[str, dict[str, Any]] = {
    # ── Claim extraction (new — STT batch entrypoint) ─────────────────────
    "claim_extractor": {
        "default_model": _FAST_MODEL,
        "description": "Selective claim extractor for live speech transcripts.",
        "instructions": (
            "You analyse a speech transcript and extract ONLY the genuinely verifiable factual claims or evasive statements that do not answer the question directly. "
            "Be extremely selective: political opinions, promises, and pure rhetoric must be ignored. "
            "Only extract concrete, checkable facts: statistics, historical events, legal claims, "
            "budget figures, or specific attributions.\n\n"
            "Always answer in the same language as the input transcript. "
            "Return ONLY valid JSON matching the provided schema."
        ),
        "tools": [],
        "schema_name": "claim_extraction_output",
        "model_cls": ClaimExtractionOutput,
    },
    # ── Routing ───────────────────────────────────────────────────────────
    "routeur": {
        "default_model": _FAST_MODEL,
        "description": "Live fact-check routing agent.",
        "instructions": (
            "You route ONE debate sentence to the relevant analysis agents. "
            "Always answer in the same language as the input sentence. "
            "Return ONLY valid JSON matching the provided schema."
        ),
        "tools": [],
        "schema_name": "routeur_output",
        "model_cls": RouteurOutput,
    },
    # ── Specialists ───────────────────────────────────────────────────────
    "statistique": {
        "default_model": _SMART_MODEL,
        "description": "Statistics and numeric claim verification specialist.",
        "instructions": (
            "You verify numeric claims by ALWAYS performing web searches first.\n\n"
            "<workflow>\n"
            "## 1. Search (MANDATORY — never skip)\n"
            "Call web_search at least once with targeted queries combining the numeric claim, "
            "relevant policy keywords, and the country name to retrieve local results. "
            "If the first search is inconclusive, refine and search again.\n\n"
            "## 2. Analyse\n"
            "Review every search result. Identify reliable institutional or media sources. "
            "Extract the most relevant figures and their publication dates.\n\n"
            "## 3. Write output\n"
            "Produce the structured JSON described in the task prompt. "
            "Populate the 'sources' field with the ACTUAL HTTP URLs you found — "
            "this is the ONLY way source links reach the final broadcast output.\n"
            "</workflow>\n\n"
            "Always answer in the same language as the input sentence. "
            "Return ONLY valid JSON matching the provided schema."
        ),
        "tools": [{"type": "web_search"}],
        "schema_name": "statistique_output",
        "model_cls": StatistiqueOutput,
    },
    "rhetorique": {
        "default_model": _FAST_MODEL,
        "description": "Rhetorical evasion analysis specialist.",
        "instructions": (
            "You detect whether the speaker answers or evades the journalist's question.\n\n"
            "<workflow>\n"
            "## 1. Read\n"
            "Parse the question and the speaker's answer carefully.\n\n"
            "## 2. Evaluate\n"
            "Determine whether the answer addresses the question directly, partially, or not at all. "
            "Political rhetoric is common — only flag clear and deliberate evasion, not partial answers.\n\n"
            "## 3. Write output\n"
            "If evasion is detected, write one concise sentence explaining it. "
            "If the question is answered (or there is no question), leave 'explication' empty.\n"
            "</workflow>\n\n"
            "Always answer in the same language as the input sentence. "
            "Return ONLY valid JSON matching the provided schema."
        ),
        "tools": [],
        "schema_name": "rhetorique_output",
        "model_cls": RhetoriqueOutput,
    },
    "coherence": {
        "default_model": _SMART_MODEL,
        "description": "Personal consistency of public statements specialist.",
        "instructions": (
            "You detect contradictions between a speaker's current claim and their past public statements "
            "by ALWAYS performing web searches first.\n\n"
            "<workflow>\n"
            "## 1. Search (MANDATORY — never skip)\n"
            "Call web_search at least once combining the speaker's name, the claim keywords, and "
            "trusted media. If the first search yields nothing decisive, refine with alternative "
            "terms (e.g. dates, policy names) and search again.\n\n"
            "## 2. Analyse\n"
            "Compare past statements found in search results against the current claim. "
            "Look for dates, context shifts, or explicit contradictions.\n\n"
            "## 3. Write output\n"
            "If a contradiction is found, briefly cite the contradictory statement with its date. "
            "If statements are coherent, leave 'explication' empty. "
            "Populate the 'sources' field with the ACTUAL HTTP URLs you found — "
            "this is the ONLY way source links reach the final broadcast output.\n"
            "</workflow>\n\n"
            "Always answer in the same language as the input sentence. "
            "Return ONLY valid JSON matching the provided schema."
        ),
        "tools": [{"type": "web_search"}],
        "schema_name": "coherence_output",
        "model_cls": CoherenceOutput,
    },
    "contexte": {
        "default_model": _SMART_MODEL,
        "description": "Contextual and factual background specialist.",
        "instructions": (
            "You provide factual background context for a political claim by ALWAYS performing web searches first.\n\n"
            "<workflow>\n"
            "## 1. Search (MANDATORY — never skip)\n"
            "Call web_search at least once with the claim keywords and the country name to retrieve "
            "local institutional and media results. The claim may be entirely false — search without "
            "assuming its validity. If the first search is insufficient, refine and search again.\n\n"
            "## 2. Analyse\n"
            "Survey all results. Extract factual background from official or trusted sources. "
            "Note what is true, what is exaggerated, and what is missing context.\n\n"
            "## 3. Write output\n"
            "Produce 5–7 factual sentences grounding the claim in real context. "
            "Populate the 'sources' field with the ACTUAL HTTP URLs you found — "
            "this is the ONLY way source links reach the final broadcast output.\n"
            "</workflow>\n\n"
            "Always answer in the same language as the input sentence. "
            "Return ONLY valid JSON matching the provided schema."
        ),
        "tools": [{"type": "web_search"}],
        "schema_name": "contexte_output",
        "model_cls": ContexteOutput,
    },
    # ── Editor (synthesis) ────────────────────────────────────────────────
    "editeur": {
        "default_model": _BEST_MODEL,
        "description": "Editor-in-chief synthesis specialist.",
        "instructions": (
            "You are the editor-in-chief of a live fact-check broadcast. "
            "You receive the raw text reports from all specialist agents and synthesize them "
            "into a final verdict.\n\n"
            "<workflow>\n"
            "## 1. Read all reports\n"
            "Read every specialist report in full. Note agreements, contradictions, and gaps.\n\n"
            "## 2. Assess overall truthfulness\n"
            "Weigh the evidence: statistical inaccuracies, rhetorical evasion, personal incoherence, "
            "and missing context. Account for normal political approximation (minor rounding → 'Exagéré', "
            "not 'Faux'). If the claim was already covered or corrected in prior context, note the redundancy.\n\n"
            "## 3. Write output\n"
            "Produce the final JSON verdict with exactly two concise TV-ready sentences when relevant. "
            "Do NOT copy URLs into the JSON — source links are extracted automatically from the "
            "specialist agents' tool-call results by the downstream system. "
            "Only include 'explications' keys that add genuine value.\n"
            "</workflow>\n\n"
            "Always answer in the same language as the input sentence. "
            "Return ONLY valid JSON matching the provided schema."
        ),
        "tools": [],
        "schema_name": "editor_output",
        "model_cls": EditorOutput,
    },
    # ── Correction detector ───────────────────────────────────────────────
    "correction": {
        "default_model": _FAST_MODEL,
        "description": "Next-sentence self-correction detector.",
        "instructions": (
            "You detect whether the next sentence explicitly corrects the current one. "
            "Always answer in the same language as the input sentence. "
            "Return ONLY valid JSON matching the provided schema."
        ),
        "tools": [],
        "schema_name": "self_correction_output",
        "model_cls": SelfCorrectionOutput,
    },
}
