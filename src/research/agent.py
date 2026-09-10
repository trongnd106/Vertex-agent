"""Deep Research Agent — orchestrates the multi-step research workflow.

Workflow:
  1. PLANNING — Analyze question, break into sub-questions, generate search queries
  2. SEARCHING — Execute parallel searches via registered providers
  3. READING — Fetch and analyze documents, extract key points and citations
  4. CROSS_REFERENCING — Compare sources for agreement / disagreement / gaps
  5. SYNTHESIZING — Produce final cited answer
  6. REFINING (deep mode only) — Iterative refinement with follow-up searches

Progress is streamed via a callback so UIs can show real-time status.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from src.research.models import (
    Citation,
    ResearchDepth,
    ResearchPlan,
    ResearchResult,
    ResearchState,
    ResearchStep,
    SearchQuery,
    SourceDocument,
)
from src.research.searcher import Searcher
from src.research.reader import DocumentReader, update_state_after_read, update_state_after_search
from src.research.synthesizer import Synthesizer

logger = logging.getLogger(__name__)

# Progress callback type
ProgressCallback = Callable[[ResearchStep, str], None]


class DeepResearchAgent:
    """Orchestrates the complete deep research workflow."""

    def __init__(
        self,
        *,
        searcher: Searcher,
        reader: DocumentReader,
        synthesizer: Synthesizer,
        llm_callable: Callable[[str, str], str] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        """Initialize the research agent.

        Args:
            searcher: The search coordinator.
            reader: The document reader / analyzer.
            synthesizer: The cross-referencer / synthesis engine.
            llm_callable: An async callable (system_prompt, user_prompt) -> str
                used for planning and refinement. If None, planning uses
                simple heuristics.
            progress_callback: Called on step transitions with
                (ResearchStep, message) for streaming UI updates.
        """
        self._searcher = searcher
        self._reader = reader
        self._synthesizer = synthesizer
        self._llm = llm_callable
        self._progress_callback = progress_callback

    def _emit_progress(self, step: ResearchStep, message: str) -> None:
        """Emit a progress update if a callback is registered."""
        if self._progress_callback:
            try:
                self._progress_callback(step, message)
            except Exception:
                logger.exception("Progress callback failed")

    async def research(
        self,
        question: str,
        depth: ResearchDepth = ResearchDepth.STANDARD,
        max_sources: int = 5,
        max_refinement_rounds: int = 3,
    ) -> ResearchResult:
        """Run the full research workflow.

        Args:
            question: The research question to investigate.
            depth: How deep to research.
            max_sources: Target number of sources to consult.
            max_refinement_rounds: Max refinement rounds in DEEP mode.

        Returns:
            A ResearchResult containing the answer, citations, and metadata.
        """
        state = ResearchState(
            question=question,
            depth=depth,
            current_step=ResearchStep.PLANNING,
            max_refinement_rounds=max_refinement_rounds,
        )

        # Step 1: Planning
        await self._run_planning(state, max_sources)

        # Step 2: Searching
        await self._run_searching(state)

        # Step 3: Reading
        await self._run_reading(state)

        # Step 4: Cross-referencing
        await self._run_cross_referencing(state)

        # Step 5: Synthesis
        result = await self._run_synthesis(state)

        # Step 6: Iterative refinement (deep mode only)
        if depth == ResearchDepth.DEEP:
            result = await self._run_refinement(state, result)

        return result

    async def research_stream(
        self,
        question: str,
        depth: ResearchDepth = ResearchDepth.STANDARD,
        max_sources: int = 5,
        max_refinement_rounds: int = 3,
    ) -> ResearchResult:
        """Run research with streaming progress.

        Progress messages are sent through the progress_callback and also
        recorded in the returned ResearchResult's metadata.
        """
        # The callback already streams; this wrapper ensures metadata is set.
        result = await self.research(
            question=question,
            depth=depth,
            max_sources=max_sources,
            max_refinement_rounds=max_refinement_rounds,
        )
        return result

    # ------------------------------------------------------------------
    # Internal workflow steps
    # ------------------------------------------------------------------

    async def _run_planning(
        self,
        state: ResearchState,
        max_sources: int,
    ) -> None:
        """Step 1: Analyze the question and build a research plan."""
        self._emit_progress(ResearchStep.PLANNING, "Analyzing research question...")

        plan: ResearchPlan | None = None

        if self._llm is not None:
            plan = await self._plan_with_llm(state.question, max_sources)

        if plan is None:
            plan = self._plan_with_heuristics(state.question, max_sources)

        state.plan = plan
        state.progress_messages.append(
            f"Research plan created: {len(plan.search_queries)} search queries, "
            f"{len(plan.sub_questions)} sub-questions"
        )
        self._emit_progress(
            ResearchStep.PLANNING,
            f"Planning complete: {len(plan.search_queries)} search queries",
        )

    async def _plan_with_llm(
        self,
        question: str,
        max_sources: int,
    ) -> ResearchPlan:
        """Use the LLM to create a detailed research plan."""
        system_prompt = (
            "You are a research planning specialist. Given a research question, "
            "break it down into sub-questions and generate effective search queries.\n\n"
            "Return your plan as:\n"
            "SUB_QUESTIONS:\n"
            "- <sub-question 1>\n"
            "- <sub-question 2>\n"
            "...\n"
            "SEARCH_QUERIES:\n"
            "- QUERY: <search query>\n"
            "  RATIONALE: <why this query>\n"
            "...\n"
        )
        user_prompt = (
            f"Research question: {question}\n"
            f"Target number of sources: {max_sources}"
        )

        try:
            result = await self._llm(system_prompt, user_prompt)
            return self._parse_llm_plan(result, question, max_sources)
        except Exception as exc:
            logger.warning("LLM planning failed: %s", exc)
            return self._plan_with_heuristics(question, max_sources)

    def _parse_llm_plan(
        self,
        text: str,
        question: str,
        max_sources: int,
    ) -> ResearchPlan:
        """Parse structured LLM plan output."""
        sub_questions: list[str] = []
        search_queries: list[SearchQuery] = []
        current_section: str | None = None
        current_query: SearchQuery | None = None

        for line in text.split("\n"):
            line = line.strip()
            upper = line.upper()

            if upper.startswith("SUB_QUESTIONS"):
                current_section = "sub_questions"
            elif upper.startswith("SEARCH_QUERIES"):
                current_section = "search_queries"
            elif current_section == "sub_questions" and line.startswith("-"):
                sub_questions.append(line.lstrip("- ").strip())
            elif current_section == "search_queries":
                if line.startswith("- QUERY:") or line.upper().startswith("QUERY:"):
                    if current_query is not None:
                        search_queries.append(current_query)
                    q = line.split(":", 1)[1].strip() if ":" in line else ""
                    current_query = SearchQuery(query=q)
                elif (
                    current_query is not None
                    and ("RATIONALE" in line.upper() or line.upper().startswith("RATIONALE:"))
                ):
                    current_query.rationale = line.split(":", 1)[1].strip() if ":" in line else ""

        if current_query is not None:
            search_queries.append(current_query)

        if not search_queries:
            search_queries = [SearchQuery(query=question)]

        return ResearchPlan(
            question=question,
            sub_questions=sub_questions,
            search_queries=search_queries,
            target_sources=max_sources,
        )

    def _plan_with_heuristics(
        self,
        question: str,
        max_sources: int,
    ) -> ResearchPlan:
        """Simple heuristic planning when no LLM is available."""
        return ResearchPlan(
            question=question,
            sub_questions=[question],
            search_queries=[SearchQuery(query=question)],
            target_sources=max_sources,
        )

    async def _run_searching(self, state: ResearchState) -> None:
        """Step 2: Execute searches."""
        if not state.plan or not state.plan.search_queries:
            state.progress_messages.append("No search queries to execute")
            return

        self._emit_progress(
            ResearchStep.SEARCHING,
            f"Searching with {len(state.plan.search_queries)} queries...",
        )

        queries = [q.query for q in state.plan.search_queries]
        results = self._searcher.search(queries, max_results_per_query=5)

        update_state_after_search(state, results)

        if results:
            self._emit_progress(
                ResearchStep.SEARCHING,
                f"Found {len(results)} unique results",
            )
        else:
            self._emit_progress(
                ResearchStep.SEARCHING,
                "No results found, continuing with available sources",
            )

    async def _run_reading(self, state: ResearchState) -> None:
        """Step 3: Fetch and analyze documents."""
        target = state.plan.target_sources if state.plan else 5
        urls_to_read = [r.url for r in state.search_results[:target]]

        if not urls_to_read:
            self._emit_progress(ResearchStep.READING, "No documents to read")
            return

        self._emit_progress(
            ResearchStep.READING,
            f"Reading {len(urls_to_read)} documents...",
        )

        url_content_pairs: list[tuple[str, str | None, str]] = []
        for url in urls_to_read:
            content = self._searcher.fetch_document(url)
            # Find the title from search results
            title = next(
                (r.title for r in state.search_results if r.url == url),
                "",
            )
            url_content_pairs.append((url, content, title))

        documents = await self._reader.read_documents(url_content_pairs)
        update_state_after_read(state, documents)

        self._emit_progress(
            ResearchStep.READING,
            f"Analyzed {len(documents)} document(s)",
        )

    async def _run_cross_referencing(self, state: ResearchState) -> None:
        """Step 4: Cross-reference sources."""
        documents = state.documents
        if len(documents) < 2:
            self._emit_progress(
                ResearchStep.CROSS_REFERENCING,
                "Need 2+ sources for cross-referencing, skipping",
            )
            # Still move to synthesis
            return

        self._emit_progress(
            ResearchStep.CROSS_REFERENCING,
            f"Cross-referencing {len(documents)} sources...",
        )

        try:
            notes = await self._synthesizer.cross_reference(documents)
            state.progress_messages.append(
                f"Cross-reference complete: {len(notes)} comparisons"
            )
            self._emit_progress(
                ResearchStep.CROSS_REFERENCING,
                f"Found {len(notes)} cross-reference insights",
            )
        except Exception as exc:
            logger.warning("Cross-referencing failed: %s", exc)
            state.progress_messages.append("Cross-referencing encountered errors")

    async def _run_synthesis(self, state: ResearchState) -> ResearchResult:
        """Step 5: Produce the final answer."""
        self._emit_progress(ResearchStep.SYNTHESIZING, "Synthesizing findings...")
        result = await self._synthesizer.synthesize(state)
        self._emit_progress(ResearchStep.DONE, "Research complete")
        return result

    async def _run_refinement(
        self,
        state: ResearchState,
        result: ResearchResult,
    ) -> ResearchResult:
        """Step 6: Iterative refinement (deep mode only).

        Identifies gaps in the current answer, generates follow-up
        searches, reads new sources, and re-synthesizes.
        """
        while state.refinement_rounds < state.max_refinement_rounds:
            state.refinement_rounds += 1

            if self._llm is None:
                break

            state.current_step = ResearchStep.REFINING
            self._emit_progress(
                ResearchStep.REFINING,
                f"Refinement round {state.refinement_rounds}/{state.max_refinement_rounds}",
            )

            gaps = await self._identify_gaps(state, result)
            if not gaps:
                state.progress_messages.append("No gaps identified, refinement complete")
                break

            state.progress_messages.append(
                f"Identified {len(gaps)} gap(s) for refinement"
            )

            # Search for each gap
            for gap in gaps:
                gap_results = self._searcher.search([gap], max_results_per_query=3)
                if gap_results:
                    existing = {r.url for r in state.search_results}
                    new_results = [r for r in gap_results if r.url not in existing]
                    state.search_results.extend(new_results)

            # Read new sources
            new_urls = [
                r.url for r in state.search_results
                if r.url not in {d.url for d in state.documents}
            ]
            if new_urls:
                new_pairs: list[tuple[str, str | None, str]] = []
                for url in new_urls[:3]:
                    content = self._searcher.fetch_document(url)
                    title = next(
                        (r.title for r in state.search_results if r.url == url),
                        "",
                    )
                    new_pairs.append((url, content, title))
                new_docs = await self._reader.read_documents(new_pairs)
                state.documents.extend(new_docs)

            # Re-synthesize
            result = await self._synthesizer.synthesize(state)
            self._emit_progress(
                ResearchStep.REFINING,
                f"Refinement round {state.refinement_rounds} complete",
            )

        return result

    async def _identify_gaps(
        self,
        state: ResearchState,
        result: ResearchResult,
    ) -> list[str]:
        """Identify gaps in the research for refinement."""
        # Unanswered sub-questions
        gaps: list[str] = []
        if state.plan:
            for sq in state.plan.sub_questions:
                if sq not in state.questions_answered:
                    gaps.append(sq)

        # Use LLM to suggest follow-up queries
        if self._llm is not None and gaps:
            system_prompt = (
                "Given the research question and current gaps, generate "
                "follow-up search queries. Return one query per line, "
                "each prefixed with QUERY:"
            )
            user_prompt = (
                f"Question: {state.question}\n"
                f"Gaps: {', '.join(gaps)}\n"
                f"Documents consulted: {len(state.documents)}\n"
                f"Answer so far: {result.answer[:500]}"
            )
            try:
                text = await self._llm(system_prompt, user_prompt)
                llm_queries = [
                    line.split(":", 1)[1].strip()
                    for line in text.split("\n")
                    if ":" in line and "QUERY" in line.upper()
                ]
                gaps.extend(llm_queries)
            except Exception:
                pass

        return gaps


def create_deep_research_agent(
    *,
    searcher: Searcher | None = None,
    reader: DocumentReader | None = None,
    synthesizer: Synthesizer | None = None,
    llm_callable: Callable[[str, str], str] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> DeepResearchAgent:
    """Factory to create a DeepResearchAgent with sensible defaults.

    If any component is omitted, a default (placeholder-based) one is created.
    """
    if searcher is None:
        from src.research.searcher import PlaceholderSearchProvider

        searcher = Searcher(providers=[PlaceholderSearchProvider()])
    if reader is None:
        reader = DocumentReader(llm_callable=llm_callable)
    if synthesizer is None:
        synthesizer = Synthesizer(llm_callable=llm_callable)

    return DeepResearchAgent(
        searcher=searcher,
        reader=reader,
        synthesizer=synthesizer,
        llm_callable=llm_callable,
        progress_callback=progress_callback,
    )


async def run_research(
    question: str,
    *,
    depth: ResearchDepth = ResearchDepth.STANDARD,
    max_sources: int = 5,
    llm_callable: Callable[[str, str], str] | None = None,
    progress_callback: ProgressCallback | None = None,
    searcher: Searcher | None = None,
) -> ResearchResult:
    """Convenience function: create an agent and run research in one call.

    Args:
        question: The research question.
        depth: Research depth.
        max_sources: Target number of sources.
        llm_callable: Optional LLM callable for planning and analysis.
        progress_callback: Optional streaming progress callback.
        searcher: Optional pre-configured searcher.

    Returns:
        A ResearchResult with the findings.
    """
    agent = create_deep_research_agent(
        searcher=searcher or Searcher(),
        reader=DocumentReader(llm_callable=llm_callable),
        synthesizer=Synthesizer(llm_callable=llm_callable),
        llm_callable=llm_callable,
        progress_callback=progress_callback,
    )
    return await agent.research(
        question=question,
        depth=depth,
        max_sources=max_sources,
    )