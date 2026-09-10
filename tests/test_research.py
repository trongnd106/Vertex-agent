"""Tests for the Deep Research Agent (Task 10.4)."""

from __future__ import annotations

import pytest

from src.research import (
    Citation,
    DeepResearchAgent,
    DocumentReader,
    ResearchDepth,
    ResearchPlan,
    ResearchResult,
    ResearchState,
    ResearchStep,
    SearchQuery,
    SearchResultItem,
    Searcher,
    SourceDocument,
    Synthesizer,
    create_deep_research_agent,
    run_research,
)
from src.research.searcher import PlaceholderSearchProvider


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def placeholder_provider() -> PlaceholderSearchProvider:
    return PlaceholderSearchProvider()


@pytest.fixture
def searcher(placeholder_provider: PlaceholderSearchProvider) -> Searcher:
    return Searcher(providers=[placeholder_provider])


@pytest.fixture
def reader() -> DocumentReader:
    return DocumentReader()


@pytest.fixture
def synthesizer() -> Synthesizer:
    return Synthesizer()


@pytest.fixture
def agent(
    searcher: Searcher,
    reader: DocumentReader,
    synthesizer: Synthesizer,
) -> DeepResearchAgent:
    return DeepResearchAgent(
        searcher=searcher,
        reader=reader,
        synthesizer=synthesizer,
    )


# ------------------------------------------------------------------
# Model tests
# ------------------------------------------------------------------

class TestModels:
    def test_search_query_defaults(self) -> None:
        q = SearchQuery(query="test query")
        assert q.query == "test query"
        assert q.rationale == ""
        assert q.source_filters == []

    def test_search_query_full(self) -> None:
        q = SearchQuery(
            query="test",
            rationale="needed for testing",
            source_filters=["example.com"],
        )
        assert q.rationale == "needed for testing"
        assert q.source_filters == ["example.com"]

    def test_search_result_item_defaults(self) -> None:
        item = SearchResultItem(title="T", url="https://x.com", snippet="snippy")
        assert item.source == "web"
        assert item.relevance_score == 0.0

    def test_source_document_defaults(self) -> None:
        doc = SourceDocument(url="https://x.com")
        assert doc.title == ""
        assert doc.content == ""
        assert doc.summary == ""
        assert doc.key_points == []
        assert doc.citations == []
        assert doc.source_type == "web"

    def test_citation_defaults(self) -> None:
        cit = Citation(source_url="https://x.com")
        assert cit.source_title == ""
        assert cit.claim == ""
        assert cit.quote == ""
        assert cit.relevance == 1.0

    def test_research_plan_defaults(self) -> None:
        plan = ResearchPlan(question="Test?")
        assert plan.sub_questions == []
        assert plan.search_queries == []
        assert plan.depth == ResearchDepth.STANDARD
        assert plan.target_sources == 5

    def test_research_state_defaults(self) -> None:
        state = ResearchState()
        assert state.question == ""
        assert state.depth == ResearchDepth.STANDARD
        assert state.current_step == ResearchStep.PLANNING
        assert state.search_results == []
        assert state.documents == []
        assert state.refinement_rounds == 0
        assert state.max_refinement_rounds == 3

    def test_research_result_defaults(self) -> None:
        result = ResearchResult(question="Test?", answer="Answer.")
        assert result.summary == ""
        assert result.citations == []
        assert result.sources_consulted == []
        assert result.depth == ResearchDepth.STANDARD
        assert result.refinement_rounds == 0
        assert result.confidence == 0.0

    def test_research_depth_enum(self) -> None:
        assert ResearchDepth.QUICK.value == "quick"
        assert ResearchDepth.STANDARD.value == "standard"
        assert ResearchDepth.DEEP.value == "deep"

    def test_research_step_enum(self) -> None:
        steps = [e.value for e in ResearchStep]
        assert "planning" in steps
        assert "searching" in steps
        assert "reading" in steps
        assert "cross_referencing" in steps
        assert "synthesizing" in steps
        assert "refining" in steps
        assert "done" in steps

    def test_citation_with_data(self) -> None:
        cit = Citation(
            source_url="https://example.com/article",
            source_title="Test Article",
            claim="The sky is blue",
            quote="The sky appears blue due to Rayleigh scattering.",
            relevance=0.95,
        )
        assert cit.source_title == "Test Article"
        assert cit.claim == "The sky is blue"
        assert cit.relevance == 0.95

    def test_source_document_with_full_data(self) -> None:
        cit = Citation(source_url="https://example.com")
        doc = SourceDocument(
            url="https://example.com/doc",
            title="Full Doc",
            content="Full content here",
            summary="A summary",
            key_points=["Point 1", "Point 2"],
            citations=[cit],
            source_type="pdf",
        )
        assert doc.title == "Full Doc"
        assert len(doc.key_points) == 2
        assert doc.citations[0].source_url == "https://example.com"
        assert doc.source_type == "pdf"

    def test_research_progress_messages(self) -> None:
        state = ResearchState()
        state.progress_messages.append("Starting research")
        state.progress_messages.append("Searching...")
        assert len(state.progress_messages) == 2
        assert "Searching" in state.progress_messages[1]
        assert state.questions_answered == set()


# ------------------------------------------------------------------
# Searcher tests
# ------------------------------------------------------------------

class TestPlaceholderSearchProvider:
    def test_search_returns_results(self, placeholder_provider: PlaceholderSearchProvider) -> None:
        results = placeholder_provider.search("test query")
        assert len(results) >= 1
        assert all(isinstance(r, SearchResultItem) for r in results)

    def test_search_with_seeded_data(self, placeholder_provider: PlaceholderSearchProvider) -> None:
        placeholder_provider.seed("python", [
            "Python is a high-level programming language.",
            "Python supports multiple programming paradigms.",
        ])
        results = placeholder_provider.search("python")
        assert len(results) == 2
        assert "Python" in results[0].title
        assert results[0].relevance_score > 0.0

    def test_search_respects_max_results(self, placeholder_provider: PlaceholderSearchProvider) -> None:
        placeholder_provider.seed("test", [f"Result {i}" for i in range(10)])
        results = placeholder_provider.search("test", max_results=3)
        assert len(results) == 3

    def test_fetch_content_returns_string(self, placeholder_provider: PlaceholderSearchProvider) -> None:
        content = placeholder_provider.fetch_content("https://example.com/doc")
        assert content is not None
        assert "Placeholder" in content
        assert "https://example.com/doc" in content


class TestSearcher:
    def test_search_no_providers(self, searcher: Searcher) -> None:
        s = Searcher()
        results = s.search(["test query"])
        assert results == []

    def test_search_with_provider(self, searcher: Searcher, placeholder_provider: PlaceholderSearchProvider) -> None:
        placeholder_provider.seed("python", ["Python is great."])
        results = searcher.search(["python"])
        assert len(results) >= 1

    def test_search_deduplicates_urls(self, placeholder_provider: PlaceholderSearchProvider) -> None:
        # Same provider returning same query twice should dedupe
        placeholder_provider.seed("unique", ["First result"])
        s = Searcher(providers=[placeholder_provider, placeholder_provider])
        results = s.search(["unique"])
        # Both providers returned the same URL "https://example.com/result-0"
        assert len(results) == 1

    def test_add_provider(self) -> None:
        s = Searcher()
        assert len(s._providers) == 0
        s.add_provider(PlaceholderSearchProvider())
        assert len(s._providers) == 1

    def test_fetch_document(self, searcher: Searcher) -> None:
        content = searcher.fetch_document("https://example.com")
        assert content is not None
        assert "Placeholder" in content

    def test_close_no_error(self, searcher: Searcher) -> None:
        searcher.close()  # Should not raise


# ------------------------------------------------------------------
# DocumentReader tests
# ------------------------------------------------------------------

class TestDocumentReader:
    @pytest.mark.asyncio
    async def test_read_document_empty_content(self, reader: DocumentReader) -> None:
        doc = await reader.read_document("https://example.com", None, "Test")
        assert doc.url == "https://example.com"
        assert doc.title == "Test"
        assert doc.content == ""
        assert doc.summary == ""

    @pytest.mark.asyncio
    async def test_read_document_with_content(self, reader: DocumentReader) -> None:
        content = (
            "Python is a high-level, general-purpose programming language. "
            "It was created by Guido van Rossum and first released in 1991. "
            "Python's design philosophy emphasizes code readability with its "
            "notable use of significant whitespace."
        )
        doc = await reader.read_document("https://example.com/python", content, "Python")
        assert doc.url == "https://example.com/python"
        assert doc.content == content
        assert len(doc.summary) > 0
        # Short content with few sentences; key_points may be empty with extractive summarizer

    @pytest.mark.asyncio
    async def test_read_documents_batch(self, reader: DocumentReader) -> None:
        pairs = [
            ("https://example.com/a", "Content A", "Doc A"),
            ("https://example.com/b", None, "Doc B"),
        ]
        docs = await reader.read_documents(pairs)
        assert len(docs) == 2
        assert docs[0].content == "Content A"
        assert docs[1].content == ""

    @pytest.mark.asyncio
    async def test_read_document_with_llm(self) -> None:
        async def fake_llm(system: str, user: str) -> str:
            return (
                "SUMMARY: A test summary.\n"
                "KEY_POINTS:\n"
                "- Important point one\n"
                "- Important point two\n"
                "CLAIMS:\n"
                "- First claim (QUOTE: direct quote here)\n"
                "- Second claim without quote\n"
            )

        reader = DocumentReader(llm_callable=fake_llm)
        doc = await reader.read_document(
            "https://example.com/test",
            "Some test content that is long enough to analyze.",
            "Test",
        )
        assert doc.summary == "A test summary."
        assert len(doc.key_points) >= 2
        assert len(doc.citations) >= 1
        assert doc.citations[0].claim == "First claim"
        assert doc.citations[0].quote == "direct quote here"


# ------------------------------------------------------------------
# Synthesizer tests
# ------------------------------------------------------------------

class TestSynthesizer:
    @pytest.mark.asyncio
    async def test_cross_reference_less_than_two(self, synthesizer: Synthesizer) -> None:
        docs = [SourceDocument(url="https://example.com/a", summary="Only one.")]
        notes = await synthesizer.cross_reference(docs)
        assert notes == []

    @pytest.mark.asyncio
    async def test_synthesize_with_no_docs(self) -> None:
        synthesizer = Synthesizer()
        state = ResearchState(question="Test?")
        result = await synthesizer.synthesize(state)
        assert result.question == "Test?"
        assert result.sources_consulted == []
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_synthesize_with_docs(self) -> None:
        synthesizer = Synthesizer()
        state = ResearchState(
            question="What is Python?",
            documents=[
                SourceDocument(
                    url="https://example.com/python",
                    title="Python",
                    summary="A programming language.",
                    key_points=["High-level", "Interpreted"],
                ),
            ],
        )
        result = await synthesizer.synthesize(state)
        assert "Python" in result.answer or "What is Python" in result.answer
        assert len(result.sources_consulted) == 1
        assert result.confidence > 0.0

    @pytest.mark.asyncio
    async def test_synthesize_with_llm(self) -> None:
        async def fake_llm(system: str, user: str) -> str:
            return "Python is a high-level programming language created by Guido van Rossum."

        synthesizer = Synthesizer(llm_callable=fake_llm)
        state = ResearchState(
            question="What is Python?",
            documents=[
                SourceDocument(
                    url="https://example.com/python",
                    title="Python",
                    summary="A programming language.",
                    key_points=["Created by Guido"],
                ),
            ],
            citations=[
                Citation(source_url="https://example.com/python", claim="Created by Guido"),
            ],
        )
        result = await synthesizer.synthesize(state)
        assert "Guido" in result.answer
        assert result.confidence > 0.0

    @pytest.mark.asyncio
    async def test_confidence_scaling(self) -> None:
        synthesizer = Synthesizer()

        # Low confidence with single doc
        state = ResearchState(
            question="Test?", documents=[SourceDocument(url="https://x.com", summary=".")]
        )
        result = await synthesizer.synthesize(state)
        assert result.confidence < 0.8

        # Higher confidence with many docs and citations
        state2 = ResearchState(
            question="Test?",
            depth=ResearchDepth.DEEP,
        )
        state2.documents = [
            SourceDocument(url=f"https://x.com/{i}", summary="Doc.") for i in range(8)
        ]
        state2.citations = [
            Citation(source_url=f"https://x.com/{i}", claim=f"Claim {i}") for i in range(5)
        ]
        result2 = await synthesizer.synthesize(state2)
        assert result2.confidence > 0.3


# ------------------------------------------------------------------
# DeepResearchAgent tests
# ------------------------------------------------------------------

class TestDeepResearchAgent:
    @pytest.mark.asyncio
    async def test_research_standard_depth(self, agent: DeepResearchAgent) -> None:
        result = await agent.research(
            "What is Python?",
            depth=ResearchDepth.STANDARD,
            max_sources=3,
        )
        assert isinstance(result, ResearchResult)
        assert result.question == "What is Python?"
        assert len(result.answer) > 0
        assert result.depth == ResearchDepth.STANDARD

    @pytest.mark.asyncio
    async def test_research_quick_depth(self, agent: DeepResearchAgent) -> None:
        result = await agent.research(
            "Test question",
            depth=ResearchDepth.QUICK,
            max_sources=2,
        )
        assert result.depth == ResearchDepth.QUICK

    @pytest.mark.asyncio
    async def test_research_deep_depth(self, agent: DeepResearchAgent) -> None:
        result = await agent.research(
            "What is Python?",
            depth=ResearchDepth.DEEP,
            max_sources=2,
        )
        assert result.depth == ResearchDepth.DEEP

    @pytest.mark.asyncio
    async def test_research_with_progress_callback(self) -> None:
        progress_steps: list[ResearchStep] = []

        def callback(step: ResearchStep, message: str) -> None:
            progress_steps.append(step)

        searcher = Searcher(providers=[PlaceholderSearchProvider()])
        agent = DeepResearchAgent(
            searcher=searcher,
            reader=DocumentReader(),
            synthesizer=Synthesizer(),
            progress_callback=callback,
        )
        result = await agent.research("Test?")
        assert len(progress_steps) > 0
        assert ResearchStep.DONE in progress_steps

    @pytest.mark.asyncio
    async def test_research_with_seeded_data(self, placeholder_provider: PlaceholderSearchProvider) -> None:
        placeholder_provider.seed("python", [
            "Python is a high-level programming language.",
            "Python supports object-oriented programming.",
        ])
        placeholder_provider.seed("programming language", [
            "A programming language is a formal language.",
        ])

        searcher = Searcher(providers=[placeholder_provider])
        agent = create_deep_research_agent(searcher=searcher)
        result = await agent.research("What is Python?")
        assert len(result.answer) > 0
        assert len(result.sources_consulted) > 0

    @pytest.mark.asyncio
    async def test_research_stream(self, agent: DeepResearchAgent) -> None:
        result = await agent.research_stream(
            "Test?",
            depth=ResearchDepth.QUICK,
        )
        assert isinstance(result, ResearchResult)
        assert result.question == "Test?"

    @pytest.mark.asyncio
    async def test_planning_with_heuristics(self, agent: DeepResearchAgent) -> None:
        plan = agent._plan_with_heuristics("Test question?", 3)
        assert isinstance(plan, ResearchPlan)
        assert plan.question == "Test question?"
        assert len(plan.search_queries) == 1
        assert plan.search_queries[0].query == "Test question?"

    @pytest.mark.asyncio
    async def test_planning_with_llm(self) -> None:
        async def fake_llm(system: str, user: str) -> str:
            return (
                "SUB_QUESTIONS:\n"
                "- What is feature X?\n"
                "- How does Y work?\n"
                "SEARCH_QUERIES:\n"
                "- QUERY: feature X explained\n"
                "  RATIONALE: Need general overview\n"
                "- QUERY: Y mechanism details\n"
                "  RATIONALE: Need technical details\n"
            )

        agent = create_deep_research_agent(llm_callable=fake_llm)
        plan = await agent._plan_with_llm("How does X work?", 5)
        assert len(plan.sub_questions) == 2
        assert len(plan.search_queries) >= 2
        assert plan.search_queries[0].query == "feature X explained"

    @pytest.mark.asyncio
    async def test_run_planning_creates_plan(self, agent: DeepResearchAgent) -> None:
        state = ResearchState(question="What is Python?")
        await agent._run_planning(state, max_sources=3)
        assert state.plan is not None
        assert state.plan.question == "What is Python?"
        assert len(state.progress_messages) > 0


# ------------------------------------------------------------------
# Factory & convenience tests
# ------------------------------------------------------------------

class TestFactory:
    @pytest.mark.asyncio
    async def test_create_with_defaults(self) -> None:
        agent = create_deep_research_agent()
        assert isinstance(agent, DeepResearchAgent)
        result = await agent.research("Test?", depth=ResearchDepth.QUICK)
        assert isinstance(result, ResearchResult)

    @pytest.mark.asyncio
    async def test_run_research_convenience(self) -> None:
        result = await run_research(
            "Test?",
            depth=ResearchDepth.QUICK,
        )
        assert isinstance(result, ResearchResult)
        assert result.question == "Test?"

    @pytest.mark.asyncio
    async def test_run_research_with_callback(self) -> None:
        steps: list[ResearchStep] = []

        def cb(step: ResearchStep, msg: str) -> None:
            steps.append(step)

        result = await run_research("Test?", depth=ResearchDepth.QUICK, progress_callback=cb)
        assert len(steps) > 0

    def test_create_agent_with_all_params(self) -> None:
        searcher = Searcher(providers=[PlaceholderSearchProvider()])
        reader = DocumentReader()
        synth = Synthesizer()

        async def fake_llm(s: str, u: str) -> str:
            return "response"

        def cb(step: ResearchStep, msg: str) -> None:
            pass

        agent = create_deep_research_agent(
            searcher=searcher,
            reader=reader,
            synthesizer=synth,
            llm_callable=fake_llm,
            progress_callback=cb,
        )
        assert isinstance(agent, DeepResearchAgent)


# ------------------------------------------------------------------
# Edge cases
# ------------------------------------------------------------------

class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_question(self, agent: DeepResearchAgent) -> None:
        result = await agent.research("", max_sources=1)
        assert isinstance(result, ResearchResult)
        assert result.question == ""

    @pytest.mark.asyncio
    async def test_very_long_question(self, agent: DeepResearchAgent) -> None:
        long_q = "What? " * 500
        result = await agent.research(long_q, depth=ResearchDepth.QUICK, max_sources=1)
        assert isinstance(result, ResearchResult)
        assert len(result.answer) > 0

    @pytest.mark.asyncio
    async def test_max_sources_zero(self, agent: DeepResearchAgent) -> None:
        result = await agent.research("Test?", max_sources=0)
        assert isinstance(result, ResearchResult)
        # Should still produce something even with no sources
        assert len(result.answer) > 0

    @pytest.mark.asyncio
    async def test_no_searcher(self) -> None:
        agent = DeepResearchAgent(
            searcher=Searcher(),  # no providers
            reader=DocumentReader(),
            synthesizer=Synthesizer(),
        )
        result = await agent.research("Test?", max_sources=2)
        assert isinstance(result, ResearchResult)
        # Without search results, it should still synthesize an empty answer
        assert len(result.answer) > 0

    @pytest.mark.asyncio
    async def test_progress_callback_exception_does_not_crash(self, agent: DeepResearchAgent) -> None:
        def failing_cb(step: ResearchStep, msg: str) -> None:
            raise ValueError("Callback failure")

        agent._progress_callback = failing_cb
        result = await agent.research("Test?", depth=ResearchDepth.QUICK, max_sources=1)
        assert isinstance(result, ResearchResult)

    @pytest.mark.asyncio
    async def test_synthesizer_llm_fallback(self) -> None:
        """When the LLM callable raises, the synthesizer falls back gracefully."""
        async def failing_llm(s: str, u: str) -> str:
            raise RuntimeError("LLM unavailable")

        synthesizer = Synthesizer(llm_callable=failing_llm)
        state = ResearchState(
            question="Test?",
            documents=[SourceDocument(url="https://x.com", summary="A source.")],
        )
        result = await synthesizer.synthesize(state)
        assert len(result.answer) > 0  # Falls back to simple synthesis