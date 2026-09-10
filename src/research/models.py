"""Data models for the Deep Research Agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ResearchDepth(str, Enum):
    """How deep the research should go."""

    QUICK = "quick"
    """Single round, few sources, short synthesis."""

    STANDARD = "standard"
    """One round of search + read + cross-reference + synthesis."""

    DEEP = "deep"
    """Multi-round iterative refinement with follow-up searches."""


class ResearchStep(str, Enum):
    """Current step in the research workflow."""

    PLANNING = "planning"
    SEARCHING = "searching"
    READING = "reading"
    CROSS_REFERENCING = "cross_referencing"
    SYNTHESIZING = "synthesizing"
    REFINING = "refining"
    DONE = "done"


@dataclass
class SearchQuery:
    """A single search query generated during research planning."""

    query: str
    """The search query string."""

    rationale: str = ""
    """Why this query was chosen."""

    source_filters: list[str] = field(default_factory=list)
    """Domain or source filters e.g. ['arxiv.org', 'en.wikipedia.org']."""


@dataclass
class SearchResultItem:
    """A single search result from a web/document search."""

    title: str
    """Result title."""

    url: str
    """Result URL."""

    snippet: str
    """Short snippet / summary of the result."""

    source: str = "web"
    """Source type: 'web', 'document', 'knowledge_base', etc."""

    relevance_score: float = 0.0
    """0.0 to 1.0 relevance score."""


@dataclass
class SourceDocument:
    """A document that was read and analyzed."""

    url: str
    """Source URL."""

    title: str = ""
    """Document title."""

    content: str = ""
    """Full text content of the document."""

    summary: str = ""
    """AI-generated summary of the document."""

    key_points: list[str] = field(default_factory=list)
    """Key points extracted from the document."""

    citations: list[Citation] = field(default_factory=list)
    """Citations within this document."""

    source_type: str = "web"
    """Type of source: 'web', 'pdf', 'document', 'knowledge_base'."""


@dataclass
class Citation:
    """A tracked citation to a source."""

    source_url: str
    """URL of the source being cited."""

    source_title: str = ""
    """Human-readable title of the source."""

    claim: str = ""
    """The specific claim or fact being cited."""

    quote: str = ""
    """Direct quote from the source (if available)."""

    relevance: float = 1.0
    """Relevance of the citation to the answer (0.0-1.0)."""


@dataclass
class ResearchPlan:
    """Plan for conducting research on a question."""

    question: str
    """The original research question."""

    sub_questions: list[str] = field(default_factory=list)
    """Sub-questions that need to be answered."""

    search_queries: list[SearchQuery] = field(default_factory=list)
    """Search queries to execute."""

    depth: ResearchDepth = ResearchDepth.STANDARD
    """Research depth."""

    target_sources: int = 5
    """Target number of sources to consult."""


@dataclass
class ResearchState:
    """Mutable state of an ongoing research session."""

    question: str = ""
    """The original research question."""

    depth: ResearchDepth = ResearchDepth.STANDARD
    """Research depth."""

    current_step: ResearchStep = ResearchStep.PLANNING
    """Current step in the workflow."""

    plan: ResearchPlan | None = None
    """The research plan."""

    search_results: list[SearchResultItem] = field(default_factory=list)
    """All search results gathered."""

    documents: list[SourceDocument] = field(default_factory=list)
    """Documents that have been read and analyzed."""

    citations: list[Citation] = field(default_factory=list)
    """All tracked citations."""

    questions_answered: set[str] = field(default_factory=set)
    """Sub-questions that have been answered."""

    refinement_rounds: int = 0
    """Number of refinement rounds completed."""

    max_refinement_rounds: int = 3
    """Maximum refinement rounds allowed."""

    progress_messages: list[str] = field(default_factory=list)
    """Progress messages for streaming."""

    errors: list[str] = field(default_factory=list)
    """Non-fatal errors encountered during research."""


@dataclass
class ResearchResult:
    """Final output of a research session."""

    question: str
    """The original research question."""

    answer: str
    """The synthesized answer."""

    summary: str = ""
    """Short summary of findings."""

    citations: list[Citation] = field(default_factory=list)
    """All citations used in the answer."""

    sources_consulted: list[str] = field(default_factory=list)
    """URLs of all sources consulted."""

    depth: ResearchDepth = ResearchDepth.STANDARD
    """Depth at which research was conducted."""

    refinement_rounds: int = 0
    """How many refinement rounds were performed."""

    confidence: float = 0.0
    """Confidence in the answer (0.0-1.0)."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional metadata about the research process."""