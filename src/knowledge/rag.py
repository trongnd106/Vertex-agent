"""RAG Engine — Retrieval-Augmented Generation for knowledge base queries."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from src.knowledge.vector_store import InMemoryVectorStore, SimilarityResult, VectorEntry, VectorStore

logger = logging.getLogger(__name__)


@dataclass
class RAGConfig:
    """Configuration for the RAG engine."""

    top_k: int = 5
    """Number of documents to retrieve."""

    min_score: float = 0.0
    """Minimum similarity score to include a document."""

    chunk_size: int = 1000
    """Character chunk size for document splitting."""

    chunk_overlap: int = 200
    """Character overlap between chunks."""


@dataclass
class RAGResult:
    """Result of a RAG query."""

    answer: str = ""
    """The generated answer."""

    sources: list[dict[str, Any]] = field(default_factory=list)
    """Source documents used, each with 'text', 'score', 'source', 'metadata'."""

    context: str = ""
    """The retrieved context that was used to generate the answer."""

    retrieval_time_ms: float = 0.0
    """Time spent on retrieval in milliseconds."""

    generation_time_ms: float = 0.0
    """Time spent on generation in milliseconds."""


class RAGEngine:
    """Retrieval-Augmented Generation engine.

    Combines a vector store for retrieval with an LLM callable for
    answer generation based on retrieved context.
    """

    def __init__(
        self,
        vector_store: VectorStore | None = None,
        embedding_fn: Callable[[str], list[float]] | None = None,
        llm_callable: Callable[[str, str], str] | None = None,
        config: RAGConfig | None = None,
    ) -> None:
        """Initialize the RAG engine.

        Args:
            vector_store: A VectorStore instance. Defaults to InMemoryVectorStore.
            embedding_fn: Callable that takes text and returns a vector.
                Required for indexing and search unless vectors are
                pre-computed.
            llm_callable: Callable (system_prompt, user_prompt) -> str.
                Required for answer generation.
            config: RAG configuration.
        """
        self._store = vector_store or InMemoryVectorStore()
        self._embedding_fn = embedding_fn
        self._llm = llm_callable
        self._config = config or RAGConfig()

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def index_text(
        self,
        text: str,
        source: str = "",
        metadata: dict[str, Any] | None = None,
        doc_id: str | None = None,
    ) -> list[str]:
        """Split, embed, and index a text document.

        Args:
            text: The document text.
            source: Source URL or document name.
            metadata: Optional metadata.
            doc_id: Optional document ID. Auto-generated if not provided.

        Returns:
            List of chunk IDs that were indexed.
        """
        import uuid

        chunks = self._chunk_text(text)

        if self._embedding_fn is None:
            logger.warning(
                "No embedding function configured; storing text without vectors"
            )
            entries: list[VectorEntry] = []
            for i, chunk in enumerate(chunks):
                cid = doc_id or str(uuid.uuid4())
                entries.append(
                    VectorEntry(
                        id=f"{cid}_chunk_{i}",
                        vector=[],
                        text=chunk,
                        metadata=metadata or {},
                        source=source,
                    )
                )
            self._store.upsert(entries)
            return [e.id for e in entries]

        entries = []
        for i, chunk in enumerate(chunks):
            cid = doc_id or str(uuid.uuid4())
            vector = self._embedding_fn(chunk)
            entries.append(
                VectorEntry(
                    id=f"{cid}_chunk_{i}",
                    vector=vector,
                    text=chunk,
                    metadata=metadata or {},
                    source=source,
                )
            )

        self._store.upsert(entries)
        return [e.id for e in entries]

    def index_documents(
        self,
        documents: list[dict[str, Any]],
    ) -> list[str]:
        """Index multiple documents at once.

        Each dict should have keys: 'text', 'source' (optional), 'metadata' (optional).
        """
        all_ids: list[str] = []
        for doc in documents:
            ids = self.index_text(
                text=doc.get("text", ""),
                source=doc.get("source", ""),
                metadata=doc.get("metadata"),
                doc_id=doc.get("id"),
            )
            all_ids.extend(ids)
        return all_ids

    # ------------------------------------------------------------------
    # Retrieval & Generation
    # ------------------------------------------------------------------

    async def query(
        self,
        question: str,
        top_k: int | None = None,
        min_score: float | None = None,
    ) -> RAGResult:
        """Run a full RAG query: retrieve context and generate an answer.

        Args:
            question: The user's question.
            top_k: Override for top_k config.
            min_score: Override for min_score config.

        Returns:
            RAGResult with the answer and source information.
        """
        import time

        t0 = time.perf_counter()

        k = top_k or self._config.top_k
        min_s = min_score if min_score is not None else self._config.min_score

        context, sources = self._retrieve(question, top_k=k, min_score=min_s)
        retrieval_time = (time.perf_counter() - t0) * 1000

        if not context:
            return RAGResult(
                answer="No relevant documents found to answer the question.",
                retrieval_time_ms=round(retrieval_time, 2),
            )

        if self._llm is None:
            answer = self._fallback_answer(question, context)
            return RAGResult(
                answer=answer,
                sources=sources,
                context=context,
                retrieval_time_ms=round(retrieval_time, 2),
            )

        t1 = time.perf_counter()
        try:
            answer = await self._llm(
                self._build_system_prompt(),
                self._build_user_prompt(question, context),
            )
        except Exception as exc:
            logger.warning("RAG generation failed: %s", exc)
            answer = self._fallback_answer(question, context)

        gen_time = (time.perf_counter() - t1) * 1000

        return RAGResult(
            answer=answer,
            sources=sources,
            context=context,
            retrieval_time_ms=round(retrieval_time, 2),
            generation_time_ms=round(gen_time, 2),
        )

    def _retrieve(
        self,
        question: str,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Retrieve relevant documents for a question.

        Returns:
            Tuple of (context_string, sources_list).
        """
        if self._embedding_fn is not None:
            query_vector = self._embedding_fn(question)
            results = self._store.search(query_vector, top_k=top_k)
        else:
            # Without embeddings, do simple keyword matching
            results = self._keyword_search(question, top_k=top_k)

        contexts: list[str] = []
        sources: list[dict[str, Any]] = []

        for r in results:
            if r.score < min_score:
                continue
            contexts.append(r.entry.text)
            sources.append({
                "text": r.entry.text[:200] + ("..." if len(r.entry.text) > 200 else ""),
                "score": round(r.score, 4),
                "source": r.entry.source,
                "metadata": r.entry.metadata,
            })

        context_str = "\n\n---\n\n".join(contexts)
        return context_str, sources

    def _keyword_search(self, query: str, top_k: int = 5) -> list[SimilarityResult]:
        """Simple keyword-based search fallback without embeddings."""
        if not isinstance(self._store, InMemoryVectorStore):
            return []

        query_lower = query.lower()
        query_words = set(query_lower.split())

        scored: list[tuple[float, VectorEntry]] = []
        for entry in self._store.list_all():
            text_lower = entry.text.lower()
            word_matches = sum(1 for w in query_words if w in text_lower)
            if word_matches > 0:
                score = word_matches / max(len(query_words), 1)
                scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:top_k]

        return [
            SimilarityResult(entry=e, score=s, rank=i + 1)
            for i, (s, e) in enumerate(top)
        ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _chunk_text(self, text: str) -> list[str]:
        """Split text into chunks of approximately chunk_size characters."""
        if len(text) <= self._config.chunk_size:
            return [text]

        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = start + self._config.chunk_size
            if end >= len(text):
                chunks.append(text[start:])
                break

            # Try to break at a sentence boundary
            chunk = text[start:end]
            last_period = max(
                chunk.rfind(". "),
                chunk.rfind("!\n"),
                chunk.rfind("?\n"),
                chunk.rfind("\n\n"),
            )
            if last_period > self._config.chunk_size // 2:
                end = start + last_period + 1
                chunk = text[start:end]

            chunks.append(chunk.strip())

            # Move start, accounting for overlap
            start = end - self._config.chunk_overlap
            if start < 0:
                start = 0

        return chunks

    def _build_system_prompt(self) -> str:
        return (
            "You are a knowledge base assistant. Answer the user's question "
            "based solely on the provided context. If the context doesn't "
            "contain enough information to answer fully, say so. "
            "Always cite your sources by referring to the document source "
            "name when available."
        )

    def _build_user_prompt(self, question: str, context: str) -> str:
        return f"Context:\n{context}\n\nQuestion:\n{question}"

    def _fallback_answer(self, question: str, context: str) -> str:
        return (
            f"Based on the retrieved documents, here is what I found:\n\n"
            f"{context[:1000]}\n\n"
            f"(Note: No LLM callable was configured for generation. "
            f"Configure an `llm_callable` for synthesized answers.)"
        )

    # ------------------------------------------------------------------
    # Management
    # ------------------------------------------------------------------

    @property
    def store(self) -> VectorStore:
        return self._store

    def clear(self) -> None:
        """Remove all indexed documents."""
        self._store.clear()

    def document_count(self) -> int:
        """Number of indexed chunks."""
        return self._store.count()