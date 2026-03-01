from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field


# ── STT / transcript ingestion schemas ────────────────────────────────────────


class TranscriptSentence(BaseModel):
    """A single sentence emitted by the STT pipeline."""

    text: str = ""
    personne: str = ""
    question_posee: str = ""
    timestamp: str = ""
    """UTC ISO-8601 timestamp of when the sentence was finalised."""


class ExtractedClaim(BaseModel):
    """A single verifiable factual claim extracted from a speech transcript.

    Only concrete, checkable facts should be represented here.
    Opinions, promises, and pure rhetoric are excluded.
    """

    affirmation: str = ""
    """The verifiable claim, reformulated clearly and concisely."""

    contexte: str = ""
    """The surrounding speech context (the sentence(s) immediately before/after)."""

    personne: str = ""
    """Name of the speaker who made the claim."""

    question_posee: str = ""
    """The journalist's question this claim was responding to (empty if none)."""

    type_claim: str = "autre"
    """Category hint: 'statistique', 'historique', 'juridique', 'budgetaire',
    'attribution', or 'autre'. Used for downstream routing optimisation."""


class ClaimExtractionOutput(BaseModel):
    """Structured output of the claim-extractor agent.

    *claims* is intentionally kept small — the extractor is instructed to be
    highly selective. An empty list is a valid result (no checkworthy facts).
    """

    claims: list[ExtractedClaim] = Field(default_factory=list)



class RouteurOutput(BaseModel):
    affirmation_propre: str = ""
    run_stats: bool = False
    run_rhetorique: bool = False
    run_coherence_personnelle: bool = False
    run_contexte: bool = False


class SourceEntry(BaseModel):
    """A single source found during web search.

    The model populates ``url`` directly from its web_search results.
    ``organization`` is the human-readable name of the source (e.g. "INSEE").
    """

    url: str = ""
    organization: str = ""


class StatistiqueOutput(BaseModel):
    """JSON schema for the statistique specialist agent.

    ``sources`` is populated by the model from its web_search results.
    Each entry has ``url`` (the actual HTTP URL found) and ``organization``
    (the human-readable source name). The downstream system uses these
    directly instead of relying on conversation tool-call extraction,
    since Mistral server-side web_search does not expose result URLs
    in the ``tool.execution.info`` field.
    """

    agent: str = "statistique"
    verdict: str = "indetermine"
    analyse_detaillee: str = ""
    sources: list[SourceEntry] = Field(default_factory=list)


class RhetoriqueOutput(BaseModel):
    agent: str = "rhetorique"
    explication: str = ""


class CoherenceOutput(BaseModel):
    agent: str = "coherence"
    explication: str = ""
    sources: list[SourceEntry] = Field(default_factory=list)


class ContexteOutput(BaseModel):
    agent: str = "contexte"
    analyse_detaillee: str = ""
    sources: list[SourceEntry] = Field(default_factory=list)


class ExplanationWithSource(BaseModel):
    texte: str = ""
    source: str = ""
    url: str = ""


class EditorExplications(BaseModel):
    statistique: ExplanationWithSource | str | None = None
    contexte: ExplanationWithSource | str | None = None
    rhetorique: str | None = None
    coherence: ExplanationWithSource | str | None = None


class EditorOutput(BaseModel):
    verdict_global: str = ""
    explications: EditorExplications | dict[str, Any] | None = None
    raison: str | None = None


class SelfCorrectionOutput(BaseModel):
    next_is_correction: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""


@dataclass
class AgentPool:
    specialist_ids: dict[str, str]
    created_agent_ids: list[str]
