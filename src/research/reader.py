"""Document reader — fetches and analyzes source documents for the research agent."""

from __future__ import annotations

import logging
from typing import Any

from src.research.models import (
    Citation,
    ResearchDepth,
    ResearchStep,
    ResearchState,
    SourceDocument,
)

logger = logging.getLogger(__name__)


class DocumentReader:
    """Reads and analyzes source documents.

    Uses an LLM (via a callable) to summarize, extract key points,
    and identify potential citations from raw document content.
    """

    def __init__(
        self,
        *,
        llm_callable: Any | None = None,
    ) -> None:
        """Initialize the document reader.

        Args:
            llm_callable: An async callable with signature
                (system_prompt: str, user_prompt: str) -> str
                that returns LLM-generated text. If None, a simple
                extractive summarizer is used instead.
        """
        self._llm = llm_callable

    async def read_document(
        self,
        url: str,
        content: str | None,
        title: str = "",
        source_type: str = "web",
    ) -> SourceDocument:
        """Fetch and analyze a single document.

        Args:
            url: The source URL.
            content: Pre-fetched document content, or None to skip.
            title: Optional document title.
            source_type: Type of the source.

        Returns:
            An analyzed SourceDocument.
        """
        if not content:
            return SourceDocument(
                url=url,
                title=title,
                content="",
                summary="",
                source_type=source_type,
            )

        if self._llm is not None:
            return await self._analyze_with_llm(url, content, title, source_type)

        return self._extractive_summary(url, content, title, source_type)

    async def read_documents(
        self,
        urls_and_contents: list[tuple[str, str | None, str]],
        source_type: str = "web",
    ) -> list[SourceDocument]:
        """Read multiple documents, potentially in parallel.

        Args:
            urls_and_contents: List of (url, content, title) tuples.
            source_type: Type of the sources.

        Returns:
            List of analyzed SourceDocuments.
        """
        docs: list[SourceDocument] = []
        for url, content, title in urls_and_contents:
            doc = await self.read_document(url, content, title, source_type)
            docs.append(doc)
        return docs

    async def _analyze_with_llm(
        self,
        url: str,
        content: str,
        title: str,
        source_type: str,
    ) -> SourceDocument:
        """Use the LLM to analyze a document."""
        system_prompt = (
            "You are a research document analyst. Given a document's content, "
            "produce a structured analysis containing:\n"
            "1. A concise summary (2-3 sentences)\n"
            "2. Key points (3-6 bullet points)\n"
            "3. Important claims that could be cited (with direct quotes if available)\n\n"
            "Format your response as:\n"
            "SUMMARY: <summary>\n"
            "KEY_POINTS:\n"
            "- <point1>\n"
            "- <point2>\n"
            "...\n"
            "CLAIMS:\n"
            "- <claim> (QUOTE: <direct quote if available>)\n"
            "..."
        )

        # Truncate content to avoid token limits
        max_chars = 15000
        truncated = content[:max_chars]
        if len(content) > max_chars:
            truncated += "\n\n[... content truncated ...]"

        user_prompt = f"Title: {title or url}\n\nContent:\n{truncated}"

        try:
            result = await self._llm(system_prompt, user_prompt)
            doc = self._parse_llm_analysis(url, content, title, source_type, result)
            return doc
        except Exception as exc:
            logger.warning("LLM analysis failed for %s: %s", url, exc)
            return self._extractive_summary(url, content, title, source_type)

    def _parse_llm_analysis(
        self,
        url: str,
        content: str,
        title: str,
        source_type: str,
        llm_output: str,
    ) -> SourceDocument:
        """Parse structured LLM output into a SourceDocument."""
        summary = ""
        key_points: list[str] = []
        citations: list[Citation] = []

        current_section: str | None = None
        for line in llm_output.split("\n"):
            line = line.strip()
            upper = line.upper()

            if upper.startswith("SUMMARY:"):
                current_section = "summary"
                summary = line[len("SUMMARY:"):].strip()
            elif upper.startswith("KEY_POINTS"):
                current_section = "key_points"
            elif upper.startswith("CLAIMS"):
                current_section = "claims"
            elif line.startswith("-") and current_section == "key_points":
                key_points.append(line.lstrip("- ").strip())
            elif line.startswith("-") and current_section == "claims":
                claim_text = line.lstrip("- ").strip()
                quote = ""
                if "(QUOTE:" in claim_text:
                    parts = claim_text.split("(QUOTE:", 1)
                    claim_text = parts[0].strip()
                    quote = parts[1].rstrip(")").strip()
                citations.append(
                    Citation(
                        source_url=url,
                        source_title=title,
                        claim=claim_text,
                        quote=quote,
                    )
                )
            elif current_section == "summary" and summary and line:
                summary += " " + line

        return SourceDocument(
            url=url,
            title=title,
            content=content,
            summary=summary,
            key_points=key_points,
            citations=citations,
            source_type=source_type,
        )

    def _extractive_summary(
        self,
        url: str,
        content: str,
        title: str,
        source_type: str,
    ) -> SourceDocument:
        """Simple extractive summarizer when no LLM is available."""
        words = content.split()
        summary = " ".join(words[:100]) + ("..." if len(words) > 100 else "")

        key_points: list[str] = []
        sentences = content.replace("\n", " ").split(". ")
        key_sentences = [
            s.strip() for s in sentences if len(s.strip().split()) > 10
        ][:5]
        for s in key_sentences[:3]:
            key_points.append(s[:150] + ("..." if len(s) > 150 else ""))

        return SourceDocument(
            url=url,
            title=title,
            content=content,
            summary=summary,
            key_points=key_points,
            source_type=source_type,
        )


def update_state_after_read(
    state: ResearchState,
    documents: list[SourceDocument],
) -> None:
    """Update research state after reading documents."""
    state.current_step = ResearchStep.CROSS_REFERENCING
    state.documents.extend(documents)
    for doc in documents:
        for cit in doc.citations:
            if cit.source_url not in {c.source_url for c in state.citations}:
                state.citations.append(cit)
    state.progress_messages.append(
        f"Read and analyzed {len(documents)} document(s)"
    )


def update_state_after_search(
    state: ResearchState,
    results: list,
) -> None:
    """Update research state after searching."""
    from src.research.models import SearchResultItem

    if results and isinstance(results[0], SearchResultItem):
        existing_urls = {r.url for r in state.search_results}
        new = [r for r in results if r.url not in existing_urls]
        state.search_results.extend(new)
        state.current_step = ResearchStep.READING
        state.progress_messages.append(
            f"Found {len(new)} new result(s) from search"
        )
    else:
        state.current_step = ResearchStep.READING
        state.progress_messages.append("Search completed")