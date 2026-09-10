"""Vector store abstraction — semantic search over embedded documents.

Provides an in-memory vector store for development/testing, and
an interface for production vector stores (Pinecone, Qdrant, etc.).
"""

from __future__ import annotations

import logging
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class VectorEntry:
    """A single entry in a vector store."""

    id: str
    """Unique identifier."""

    vector: list[float]
    """The embedding vector."""

    text: str = ""
    """Original text content."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Arbitrary metadata."""

    source: str = ""
    """Source URL or document name."""


@dataclass
class SimilarityResult:
    """A similarity search result."""

    entry: VectorEntry
    """The matched entry."""

    score: float
    """Similarity score (1.0 = exact match, 0.0 = orthogonal)."""

    rank: int = 0
    """Rank in the result list."""


class VectorStore(ABC):
    """Abstract base for vector stores."""

    @abstractmethod
    def upsert(self, entries: list[VectorEntry]) -> None:
        """Insert or update entries."""
        ...

    @abstractmethod
    def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        filter_: dict[str, Any] | None = None,
    ) -> list[SimilarityResult]:
        """Search for similar vectors."""
        ...

    @abstractmethod
    def delete(self, ids: list[str]) -> None:
        """Delete entries by ID."""
        ...

    @abstractmethod
    def count(self) -> int:
        """Total number of entries."""
        ...

    def clear(self) -> None:
        """Remove all entries."""
        ...


class InMemoryVectorStore(VectorStore):
    """Simple in-memory vector store using cosine similarity.

    Suitable for development, testing, and small-scale use.
    """

    def __init__(self) -> None:
        self._entries: dict[str, VectorEntry] = {}

    def upsert(self, entries: list[VectorEntry]) -> None:
        for entry in entries:
            self._entries[entry.id] = entry

    def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        filter_: dict[str, Any] | None = None,
    ) -> list[SimilarityResult]:
        if not self._entries:
            return []

        scored: list[tuple[float, VectorEntry]] = []
        for entry in self._entries.values():
            if filter_ and not self._matches_filter(entry, filter_):
                continue
            score = self._cosine_similarity(query_vector, entry.vector)
            scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:top_k]

        return [
            SimilarityResult(entry=e, score=s, rank=i + 1)
            for i, (s, e) in enumerate(top)
        ]

    def delete(self, ids: list[str]) -> None:
        for entry_id in ids:
            self._entries.pop(entry_id, None)

    def count(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        self._entries.clear()

    def get(self, entry_id: str) -> VectorEntry | None:
        """Get a single entry by ID."""
        return self._entries.get(entry_id)

    def list_all(self) -> list[VectorEntry]:
        """List all entries."""
        return list(self._entries.values())

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if len(a) != len(b):
            raise ValueError(f"Vector dimension mismatch: {len(a)} vs {len(b)}")

        dot = sum(ai * bi for ai, bi in zip(a, b))
        norm_a = math.sqrt(sum(ai * ai for ai in a))
        norm_b = math.sqrt(sum(bi * bi for bi in b))

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot / (norm_a * norm_b)

    @staticmethod
    def _matches_filter(entry: VectorEntry, filter_: dict[str, Any]) -> bool:
        """Check if an entry matches a filter dict."""
        for key, value in filter_.items():
            if key in entry.metadata:
                if entry.metadata[key] != value:
                    return False
            elif key == "source" and entry.source != value:
                return False
            elif key not in ("source",) and key not in entry.metadata:
                return False
        return True