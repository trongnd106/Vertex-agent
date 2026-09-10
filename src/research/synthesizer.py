"""Synthesizer — cross-references sources and produces the final research answer."""

from __future__ import annotations

import logging
from typing import Any

from src.research.models import (
    Citation,
    ResearchDepth,
    ResearchResult,
    ResearchState,
    ResearchStep,
    SourceDocument,
)

logger = logging.getLogger(__name__)


class Synthesizer:
    """Cross-references multiple sources and synthesizes a final answer.

    Uses an LLM (via a callable) to compare, contrast, and merge findings
    from different sources into a coherent, cited answer.
    """

    def __init__(
        self,
        *,
        llm_callable: Any | None = None,
    ) -> None:
        """Initialize the synthesizer.

        Args:
            llm_callable: An async callable with signature
                (system_prompt: str, user_prompt: str) -> str.
                If None, a simple concatenation-based fallback is used.
        """
        self._llm = llm_callable

    async def cross_reference(
        self,
        documents: list[SourceDocument],
    ) -> list[dict[str, Any]]:
        """Compare multiple sources to find agreements, disagreements, and gaps.

        Returns a list of cross-reference notes, each with:
            - topic: str — what was compared
            - agreement: bool — whether sources agree
            - sources: list[str] — URLs involved
            - detail: str — explanation
        """
        if len(documents) < 2:
            return []

        if self._llm is None:
            return self._simple_cross_ref(documents)

        system_prompt = (
            "You are a research cross-referencer. Given multiple source documents "
            "on the same topic, identify:\n"
            "1. Areas of agreement across sources\n"
            "2. Areas of disagreement or contradiction\n"
            "3. Unique insights from individual sources\n"
            "4. Gaps in coverage\n\n"
            "For each finding, list:\n"
            "TOPIC: <topic>\n"
            "AGREEMENT: yes|no|partial\n"
            "SOURCES: <url1>, <url2>, ...\n"
            "DETAIL: <explanation>\n"
        )

        docs_text = ""
        for i, doc in enumerate(documents):
            snippet = (
                f"--- Document {i+1} ---\n"
                f"URL: {doc.url}\n"
                f"Title: {doc.title}\n"
                f"Summary: {doc.summary}\n"
                f"Key Points: {', '.join(doc.key_points[:3])}\n"
            )
            docs_text += snippet + "\n"

        try:
            result = await self._llm(system_prompt, docs_text)
            return self._parse_cross_ref(result, documents)
        except Exception as exc:
            logger.warning("Cross-reference LLM call failed: %s", exc)
            return self._simple_cross_ref(documents)

    async def synthesize(
        self,
        state: ResearchState,
    ) -> ResearchResult:
        """Produce the final synthesized answer from all research data.

        Args:
            state: The current research state.

        Returns:
            A ResearchResult with the answer and metadata.
        """
        state.current_step = ResearchStep.SYNTHESIZING
        state.progress_messages.append("Synthesizing final answer...")

        if self._llm is None:
            answer = self._simple_synthesize(state)
        else:
            try:
                answer = await self._llm_synthesize(state)
            except Exception as exc:
                logger.warning("LLM synthesis failed: %s", exc)
                answer = self._simple_synthesize(state)

        confidence = self._compute_confidence(state)

        state.current_step = ResearchStep.DONE
        state.progress_messages.append("Research complete")

        return ResearchResult(
            question=state.question,
            answer=answer,
            summary=answer.split("\n\n")[0] if answer else "",
            citations=list(state.citations),
            sources_consulted=[d.url for d in state.documents],
            depth=state.depth,
            refinement_rounds=state.refinement_rounds,
            confidence=confidence,
        )

    async def _llm_synthesize(
        self,
        state: ResearchState,
    ) -> str:
        """Use the LLM to generate a synthesis."""
        system_prompt = (
            "You are a research synthesis specialist. Your task is to produce "
            "a well-structured, comprehensive answer to the research question "
            "based on the provided source materials.\n\n"
            "Guidelines:\n"
            "- Synthesize across sources, don't just list them\n"
            "- Highlight consensus and note disagreements\n"
            "- Include specific citations like [Source: URL]\n"
            "- Use multiple paragraphs and clear section headers\n"
            "- Be objective and balanced\n"
            "- Mark uncertainty when sources conflict or are insufficient\n"
        )

        user_prompt = self._build_user_prompt(state)

        return await self._llm(system_prompt, user_prompt)

    def _build_user_prompt(self, state: ResearchState) -> str:
        """Build the user prompt content from research state."""
        sections: list[str] = [
            f"Research Question: {state.question}",
            f"Depth: {state.depth.value}",
        ]

        if state.documents:
            sections.append("\n--- Source Documents ---")
            for doc in state.documents:
                sections.append(
                    f"\nURL: {doc.url}\n"
                    f"Title: {doc.title}\n"
                    f"Summary: {doc.summary}\n"
                    f"Key Points:\n"
                    + "\n".join(f"  - {kp}" for kp in doc.key_points)
                )

        if state.citations:
            sections.append("\n--- Citations ---")
            for cit in state.citations:
                sections.append(f"  - [{cit.source_title}]({cit.source_url}): {cit.claim}")

        return "\n".join(sections)

    def _simple_synthesize(self, state: ResearchState) -> str:
        """Simple concatenation-based fallback synthesis."""
        lines = [f"# Research: {state.question}", ""]

        if state.documents:
            lines.append(f"## Summary of {len(state.documents)} Sources")
            lines.append("")
            for doc in state.documents:
                lines.append(f"### {doc.title or doc.url}")
                lines.append("")
                if doc.summary:
                    lines.append(doc.summary)
                if doc.key_points:
                    lines.append("Key points:")
                    for kp in doc.key_points:
                        lines.append(f"- {kp}")
                lines.append("")
        else:
            lines.append("No sources were consulted.")

        lines.append("---")
        lines.append("*This is a simple concatenation-based synthesis. "
                     "Configure an LLM callable for deeper analysis.*")

        return "\n".join(lines)

    def _simple_cross_ref(
        self,
        documents: list[SourceDocument],
    ) -> list[dict[str, Any]]:
        """Simple cross-reference without LLM."""
        notes: list[dict[str, Any]] = []
        for i, doc1 in enumerate(documents):
            for doc2 in documents[i + 1:]:
                common_topics = set(doc1.key_points) & set(doc2.key_points)
                if common_topics:
                    notes.append({
                        "topic": " | ".join(list(common_topics)[:2]),
                        "agreement": True,
                        "sources": [doc1.url, doc2.url],
                        "detail": "Sources share common key points.",
                    })
                else:
                    # Check for content overlap by summary words
                    words1 = set(doc1.summary.lower().split())
                    words2 = set(doc2.summary.lower().split())
                    overlap = words1 & words2
                    if len(overlap) > 10:
                        notes.append({
                            "topic": "content overlap",
                            "agreement": True,
                            "sources": [doc1.url, doc2.url],
                            "detail": f"Summaries share {len(overlap)} common words.",
                        })
        return notes

    def _parse_cross_ref(
        self,
        text: str,
        documents: list[SourceDocument],
    ) -> list[dict[str, Any]]:
        """Parse structured cross-reference output."""
        notes: list[dict[str, Any]] = []
        current: dict[str, Any] = {}

        for line in text.split("\n"):
            line = line.strip()
            if line.upper().startswith("TOPIC:"):
                if current:
                    notes.append(current)
                current = {"topic": line[len("TOPIC:"):].strip()}
            elif line.upper().startswith("AGREEMENT:"):
                val = line[len("AGREEMENT:"):].strip().lower()
                current["agreement"] = val in ("yes", "true", "partial")
            elif line.upper().startswith("SOURCES:"):
                raw = line[len("SOURCES:"):].strip()
                current["sources"] = [s.strip().rstrip(",") for s in raw.split(",")]
            elif line.upper().startswith("DETAIL:"):
                current["detail"] = line[len("DETAIL:"):].strip()

        if current:
            notes.append(current)

        return notes

    def _compute_confidence(self, state: ResearchState) -> float:
        """Compute a confidence score (0.0-1.0) based on research quality."""
        if not state.documents:
            return 0.0

        score = 0.0

        # Number of sources
        source_count = len(state.documents)
        score += min(source_count / 10, 0.3)

        # Citation coverage
        if state.citations:
            score += min(len(state.citations) / 5, 0.2)

        # Depth bonus
        depth_map = {
            ResearchDepth.QUICK: 0.1,
            ResearchDepth.STANDARD: 0.2,
            ResearchDepth.DEEP: 0.3,
        }
        score += depth_map.get(state.depth, 0.1)

        # Answers sub-questions
        if state.questions_answered:
            score += min(len(state.questions_answered) / 3, 0.2)

        return min(score, 1.0)


def update_state_after_synthesis(
    state: ResearchState,
    result: ResearchResult,
) -> None:
    """Update research state after synthesis."""
    state.current_step = ResearchStep.DONE
    if result.citations:
        state.citations.extend(result.citations)
    state.progress_messages.append("Synthesis complete")