"""Knowledge Base integration — RAG, vector store, document processing."""

from src.knowledge.rag import RAGEngine, RAGResult, RAGConfig
from src.knowledge.vector_store import (
    VectorStore,
    InMemoryVectorStore,
    VectorEntry,
    SimilarityResult,
)

__all__ = [
    "RAGEngine",
    "RAGResult",
    "RAGConfig",
    "VectorStore",
    "InMemoryVectorStore",
    "VectorEntry",
    "SimilarityResult",
]