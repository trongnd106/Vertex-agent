"""Tests for Knowledge Base integration (Task 10.5) — RAG and vector store."""

from __future__ import annotations

import math

import pytest

from src.knowledge import (
    InMemoryVectorStore,
    RAGConfig,
    RAGEngine,
    RAGResult,
    SimilarityResult,
    VectorEntry,
    VectorStore,
)


# ------------------------------------------------------------------
# VectorStore tests
# ------------------------------------------------------------------

class TestInMemoryVectorStore:
    def test_upsert_and_search(self) -> None:
        store = InMemoryVectorStore()
        v1 = [1.0, 0.0, 0.0]
        v2 = [0.0, 1.0, 0.0]
        store.upsert([
            VectorEntry(id="1", vector=v1, text="Document A"),
            VectorEntry(id="2", vector=v2, text="Document B"),
        ])
        assert store.count() == 2

    def test_search_returns_sorted_results(self) -> None:
        store = InMemoryVectorStore()
        store.upsert([
            VectorEntry(id="1", vector=[1.0, 0.0], text="Related doc"),
            VectorEntry(id="2", vector=[0.0, 1.0], text="Unrelated doc"),
        ])
        results = store.search([1.0, 0.0], top_k=2)
        assert len(results) == 2
        assert results[0].entry.id == "1"
        assert results[0].score > results[1].score

    def test_search_empty_store(self) -> None:
        store = InMemoryVectorStore()
        results = store.search([1.0, 0.0])
        assert results == []

    def test_delete(self) -> None:
        store = InMemoryVectorStore()
        store.upsert([VectorEntry(id="1", vector=[1.0, 0.0])])
        store.delete(["1"])
        assert store.count() == 0

    def test_clear(self) -> None:
        store = InMemoryVectorStore()
        store.upsert([VectorEntry(id="1", vector=[1.0, 0.0])])
        store.clear()
        assert store.count() == 0

    def test_get(self) -> None:
        store = InMemoryVectorStore()
        store.upsert([VectorEntry(id="1", vector=[1.0, 0.0], text="Hello")])
        entry = store.get("1")
        assert entry is not None
        assert entry.text == "Hello"
        assert store.get("nonexistent") is None

    def test_list_all(self) -> None:
        store = InMemoryVectorStore()
        store.upsert([
            VectorEntry(id="1", vector=[1.0, 0.0]),
            VectorEntry(id="2", vector=[0.0, 1.0]),
        ])
        assert len(store.list_all()) == 2

    def test_search_with_filter(self) -> None:
        store = InMemoryVectorStore()
        store.upsert([
            VectorEntry(id="1", vector=[1.0, 0.0], metadata={"lang": "en"}, source="wiki"),
            VectorEntry(id="2", vector=[0.0, 1.0], metadata={"lang": "fr"}, source="wiki"),
        ])
        results = store.search([1.0, 0.0], filter_={"lang": "en"})
        assert len(results) == 1
        assert results[0].entry.id == "1"

    def test_search_without_results_for_mismatched_filter(self) -> None:
        store = InMemoryVectorStore()
        store.upsert([VectorEntry(id="1", vector=[1.0, 0.0], metadata={"lang": "en"})])
        results = store.search([1.0, 0.0], filter_={"lang": "de"})
        assert len(results) == 0

    def test_cosine_similarity_identical(self) -> None:
        score = InMemoryVectorStore._cosine_similarity([1.0, 0.0], [1.0, 0.0])
        assert math.isclose(score, 1.0)

    def test_cosine_similarity_orthogonal(self) -> None:
        score = InMemoryVectorStore._cosine_similarity([1.0, 0.0], [0.0, 1.0])
        assert math.isclose(score, 0.0)

    def test_cosine_similarity_opposite(self) -> None:
        score = InMemoryVectorStore._cosine_similarity([1.0, 0.0], [-1.0, 0.0])
        assert math.isclose(score, -1.0)

    def test_cosine_similarity_zero_vector(self) -> None:
        score = InMemoryVectorStore._cosine_similarity([0.0, 0.0], [1.0, 0.0])
        assert math.isclose(score, 0.0)

    def test_upsert_replaces_existing(self) -> None:
        store = InMemoryVectorStore()
        store.upsert([VectorEntry(id="1", vector=[1.0, 0.0], text="Old")])
        store.upsert([VectorEntry(id="1", vector=[1.0, 0.0], text="New")])
        assert store.get("1").text == "New"


# ------------------------------------------------------------------
# RAGEngine tests
# ------------------------------------------------------------------

class TestRAGEngine:
    def test_index_text_without_embeddings(self) -> None:
        engine = RAGEngine()
        ids = engine.index_text("This is a test document.", source="test.txt")
        assert len(ids) > 0
        assert engine.document_count() > 0

    def test_index_and_keyword_search(self) -> None:
        engine = RAGEngine()
        engine.index_text("Python is a programming language.", source="python.txt")
        engine.index_text("Cats are cute animals.", source="cats.txt")

        result = engine.store.search([], top_k=5)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_query_no_matches(self) -> None:
        engine = RAGEngine()
        result = await engine.query("Something about nothing")
        assert "No relevant documents" in result.answer

    @pytest.mark.asyncio
    async def test_query_with_keyword_fallback(self) -> None:
        engine = RAGEngine()
        engine.index_text("Python is a high-level programming language.", source="python.txt")
        result = await engine.query("What is Python?")
        # Should find "python" via keyword matching
        assert "Python" in result.answer or "python" in result.context.lower()

    @pytest.mark.asyncio
    async def test_query_with_llm(self) -> None:
        async def fake_llm(system: str, user: str) -> str:
            return "Python is a high-level programming language."

        engine = RAGEngine(llm_callable=fake_llm)
        engine.index_text("Python is a high-level programming language by Guido van Rossum.", source="wiki")
        result = await engine.query("What is Python?")
        assert "programming" in result.answer
        assert result.retrieval_time_ms > 0

    def test_chunk_text_short(self) -> None:
        engine = RAGEngine()
        chunks = engine._chunk_text("Short text.")
        assert len(chunks) == 1

    def test_chunk_text_long(self) -> None:
        engine = RAGEngine(config=RAGConfig(chunk_size=50, chunk_overlap=10))
        text = "Word. " * 30
        chunks = engine._chunk_text(text)
        assert len(chunks) > 1

    def test_index_documents_batch(self) -> None:
        engine = RAGEngine()
        docs = [
            {"text": "Document one content.", "source": "doc1.txt"},
            {"text": "Document two content.", "source": "doc2.txt"},
        ]
        ids = engine.index_documents(docs)
        assert len(ids) >= 2
        assert engine.document_count() >= 2

    def test_clear(self) -> None:
        engine = RAGEngine()
        engine.index_text("Test.", source="t.txt")
        assert engine.document_count() > 0
        engine.clear()
        assert engine.document_count() == 0

    def test_config_defaults(self) -> None:
        config = RAGConfig()
        assert config.top_k == 5
        assert config.min_score == 0.0
        assert config.chunk_size == 1000
        assert config.chunk_overlap == 200

    def test_store_property(self) -> None:
        engine = RAGEngine()
        assert isinstance(engine.store, VectorStore)

    def test_keyword_search_uses_word_matches(self) -> None:
        engine = RAGEngine()
        engine.index_text("The quick brown fox jumps over the lazy dog.", source="fox.txt")
        engine.index_text("Python programming is fun and educational.", source="python.txt")

        results = engine._keyword_search("fox dog", top_k=5)
        assert len(results) > 0
        # "fox" and "dog" should match the first document
        assert results[0].entry.source == "fox.txt"


# ------------------------------------------------------------------
# SimilarityResult tests
# ------------------------------------------------------------------

class TestSimilarityResult:
    def test_defaults(self) -> None:
        entry = VectorEntry(id="1", vector=[1.0, 0.0])
        result = SimilarityResult(entry=entry, score=0.95)
        assert result.score == 0.95
        assert result.rank == 0
        assert result.entry.id == "1"

    def test_with_rank(self) -> None:
        entry = VectorEntry(id="1", vector=[1.0, 0.0])
        result = SimilarityResult(entry=entry, score=0.8, rank=3)
        assert result.rank == 3


# ------------------------------------------------------------------
# VectorEntry tests
# ------------------------------------------------------------------

class TestVectorEntry:
    def test_defaults(self) -> None:
        entry = VectorEntry(id="1", vector=[1.0, 0.0])
        assert entry.text == ""
        assert entry.metadata == {}
        assert entry.source == ""

    def test_full_entry(self) -> None:
        entry = VectorEntry(
            id="1",
            vector=[1.0, 0.0],
            text="Content",
            metadata={"author": "test"},
            source="test.txt",
        )
        assert entry.text == "Content"
        assert entry.metadata["author"] == "test"
        assert entry.source == "test.txt"