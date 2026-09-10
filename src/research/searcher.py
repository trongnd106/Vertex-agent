"""Web search abstraction layer for the research agent.

Provides a pluggable search provider interface with a built-in fallback
that returns informative placeholders when no real search backend is configured.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from src.config import config

from src.research.models import SearchResultItem


class WebSearchProvider(ABC):
    """Abstract base for web search providers."""

    @abstractmethod
    def search(self, query: str, max_results: int = 5) -> list[SearchResultItem]:
        """Execute a search and return results."""
        ...

    @abstractmethod
    def fetch_content(self, url: str) -> str | None:
        """Fetch the text content of a URL."""
        ...


class Searcher:
    """High-level searcher that coordinates multiple search providers."""

    def __init__(
        self,
        providers: list[WebSearchProvider] | None = None,
        user_id: str | None = None,
    ) -> None:
        self._providers = providers or []
        self.user_id = user_id

    def add_provider(self, provider: WebSearchProvider) -> None:
        """Register a search provider."""
        self._providers.append(provider)

    def search(
        self,
        queries: list[str],
        max_results_per_query: int = 5,
    ) -> list[SearchResultItem]:
        """Execute multiple search queries across all providers.

        Returns deduplicated results sorted by relevance.
        """
        seen_urls: set[str] = set()
        all_results: list[SearchResultItem] = []

        for query in queries:
            for provider in self._providers:
                try:
                    results = provider.search(query, max_results=max_results_per_query)
                    for r in results:
                        if r.url not in seen_urls:
                            seen_urls.add(r.url)
                            all_results.append(r)
                except Exception as exc:
                    # Non-fatal: log and continue with other providers
                    import logging
                    logging.getLogger(__name__).warning(
                        "Search provider %s failed for query %r: %s",
                        type(provider).__name__,
                        query,
                        exc,
                    )

        # Sort by relevance score descending
        all_results.sort(key=lambda r: r.relevance_score, reverse=True)
        return all_results

    def fetch_document(self, url: str) -> str | None:
        """Fetch a document's content from any provider that can."""
        for provider in self._providers:
            try:
                content = provider.fetch_content(url)
                if content is not None:
                    return content
            except Exception:
                continue
        return None

    def close(self) -> None:
        """Release any resources held by providers."""
        for p in self._providers:
            if hasattr(p, "close"):
                p.close()


class PlaceholderSearchProvider(WebSearchProvider):
    """Fallback search provider that returns mock results.

    Used when no real search backend (Tavily, SerpAPI, etc.) is configured.
    """

    def __init__(self) -> None:
        super().__init__()
        self._snippets: dict[str, list[str]] = {}

    def seed(self, query_keyword: str, snippets: list[str]) -> None:
        """Pre-load snippets for testing or offline demo."""
        key = query_keyword.lower().strip()
        self._snippets.setdefault(key, []).extend(snippets)

    def search(self, query: str, max_results: int = 5) -> list[SearchResultItem]:
        """Return seeded results or a generic placeholder."""
        key = query.lower().strip()
        seeded = self._snippets.get(key, [])

        if seeded:
            return [
                SearchResultItem(
                    title=f"Result about: {seeded[i][:60]}",
                    url=f"https://example.com/result-{i}",
                    snippet=seeded[i],
                    relevance_score=max(0.0, 1.0 - (i * 0.1)),
                )
                for i in range(min(len(seeded), max_results))
            ]

        return [
            SearchResultItem(
                title=f"Placeholder: {query[:60]}",
                url=f"https://placeholder.example.com/search?q={query}",
                snippet=f"This is a placeholder result for query: {query}. "
                f"Configure a real search provider (e.g. Tavily, SerpAPI) "
                f"to get live results.",
                relevance_score=0.5,
            )
        ]

    def fetch_content(self, url: str) -> str | None:
        """Return a placeholder document body."""
        return (
            f"# Placeholder Document\n\n"
            f"This is placeholder content fetched from {url}.\n\n"
            f"Configure a real search provider to receive actual content.\n"
        )


class TavilySearchProvider(WebSearchProvider):
    """Search provider backed by Tavily API."""

    def __init__(self, api_key: str | None = None) -> None:
        super().__init__()
        self._api_key = api_key or config.TAVILY_API_KEY
        self._client: Any | None = None

    def _ensure_client(self) -> Any:
        if self._client is None:
            try:
                from tavily import TavilyClient
                self._client = TavilyClient(api_key=self._api_key)
            except ImportError:
                raise RuntimeError(
                    "tavily package is not installed. Install it via `pip install tavily`."
                )
        return self._client

    def search(self, query: str, max_results: int = 5) -> list[SearchResultItem]:
        client = self._ensure_client()
        response = client.search(query=query, max_results=max_results)
        results: list[SearchResultItem] = []
        for item in response.get("results", []):
            results.append(
                SearchResultItem(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("content", item.get("snippet", "")),
                    relevance_score=item.get("score", 0.5),
                )
            )
        return results

    def fetch_content(self, url: str) -> str | None:
        """Tavily doesn't directly support content fetch; return None."""
        return None


class DuckDuckGoSearchProvider(WebSearchProvider):
    """Search provider backed by DuckDuckGo (free, no API key needed)."""

    def __init__(self) -> None:
        super().__init__()
        self._ddgs: Any = None

    def _ensure_ddgs(self) -> Any:
        if self._ddgs is None:
            try:
                from duckduckgo_search import DDGS
                self._ddgs = DDGS()
            except ImportError:
                raise RuntimeError(
                    "duckduckgo_search is not installed. "
                    "Install it via `pip install duckduckgo-search`."
                )
        return self._ddgs

    def search(self, query: str, max_results: int = 5) -> list[SearchResultItem]:
        ddgs = self._ensure_ddgs()
        raw = list(ddgs.text(query, max_results=max_results))
        results: list[SearchResultItem] = []
        for i, item in enumerate(raw):
            results.append(
                SearchResultItem(
                    title=item.get("title", ""),
                    url=item.get("href", ""),
                    snippet=item.get("body", ""),
                    relevance_score=max(0.0, 1.0 - (i * 0.1)),
                )
            )
        return results

    def fetch_content(self, url: str) -> str | None:
        """DuckDuckGo doesn't support content fetch; return None."""
        return None