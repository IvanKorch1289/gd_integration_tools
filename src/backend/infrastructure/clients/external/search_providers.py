"""Search providers — Perplexity, Tavily, SearXNG с fallback chain."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any

from src.backend.core.logging import get_logger
__all__ = (
    "BaseSearchProvider",
    "PerplexityProvider",
    "SearXNGProvider",
    "TavilyProvider",
    "WebSearchService",
    "get_web_search_service",
)

logger = get_logger(__name__)


class BaseSearchProvider(ABC):
    """Abstract search provider interface."""

    name: str = "base"

    @abstractmethod
    async def search(
        self, query: str, max_results: int = 5
    ) -> list[dict[str, Any]]:
        """Search for query.

        Args:
            query: Search query.
            max_results: Maximum results.

        Returns:
            List of search results.
        """
        ...

    @abstractmethod
    async def deep_research(self, query: str) -> dict[str, Any]:
        """Perform deep research on query.

        Args:
            query: Research query.

        Returns:
            Research results.
        """
        ...


class PerplexityProvider(BaseSearchProvider):
    """Perplexity search provider."""

    name = "perplexity"

    def __init__(self, api_key: str, model: str = "sonar") -> None:
        self._api_key = api_key
        self._model = model

    async def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        """Search via Perplexity API.

        Args:
            query: Search query.
            max_results: Maximum results.

        Returns:
            List of search results with content and citations.
        """
        from src.backend.core.net.migration_helper import make_http_client

        async with make_http_client(timeout=30, plugin="perplexity") as client:
            response = await client.post(
                "https://api.perplexity.ai/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": query}],
                    "max_tokens": 1024,
                },
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            citations = data.get("citations", [])
            return [{"content": content, "citations": citations, "provider": self.name}]

    async def deep_research(self, query: str) -> dict[str, Any]:
        """Perform deep research via Perplexity.

        Args:
            query: Research query.

        Returns:
            Research results with query and provider info.
        """
        results = await self.search(query, max_results=10)
        return {"query": query, "results": results, "provider": self.name}


class TavilyProvider(BaseSearchProvider):
    """Tavily search provider."""

    name = "tavily"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        """Search via Tavily API.

        Args:
            query: Search query.
            max_results: Maximum results.

        Returns:
            List of search results.
        """
        from src.backend.core.net.migration_helper import make_http_client

        async with make_http_client(timeout=30, plugin="tavily") as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self._api_key,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "basic",
                },
            )
            response.raise_for_status()
            data = response.json()
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "content": r.get("content", ""),
                    "score": r.get("score", 0),
                    "provider": self.name,
                }
                for r in data.get("results", [])
            ]

    async def deep_research(self, query: str) -> dict[str, Any]:
        """Perform deep research via Tavily.

        Args:
            query: Research query.

        Returns:
            Research results with query and provider info.
        """
        from src.backend.core.net.migration_helper import make_http_client

        async with make_http_client(timeout=60, plugin="tavily") as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self._api_key,
                    "query": query,
                    "max_results": 10,
                    "search_depth": "advanced",
                    "include_raw_content": True,
                },
            )
            response.raise_for_status()
            return response.json()


class SearXNGProvider(BaseSearchProvider):
    """SearXNG meta-search provider (self-hosted, free, unlimited).

    Privacy-first, aggregates Google/Bing/DuckDuckGo/Wikipedia.
    Suitable for air-gapped environments.

    Args:
        base_url: SearXNG instance URL.
        engines: Search engines to use.
        timeout: HTTP timeout in seconds.
    """

    name = "searxng"

    def __init__(
        self, base_url: str, engines: list[str] | None = None, timeout: float = 15.0
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._engines = engines or ["google", "bing", "duckduckgo"]
        self._timeout = timeout

    async def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        """Search via SearXNG.

        Args:
            query: Search query.
            max_results: Maximum results.

        Returns:
            List of search results.
        """
        from src.backend.core.net.migration_helper import make_http_client

        params = {"q": query, "format": "json", "engines": ",".join(self._engines)}
        async with make_http_client(timeout=self._timeout, plugin="searxng") as client:
            response = await client.get(f"{self._base_url}/", params=params)
            response.raise_for_status()
            data = response.json()
            results = data.get("results", [])[:max_results]
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "content": r.get("content", ""),
                    "engine": r.get("engine", ""),
                }
                for r in results
            ]

    async def deep_research(self, query: str) -> dict[str, Any]:
        """SearXNG не поддерживает deep-research; возвращает обычный search.

        Метод обеспечивает совместимость с BaseSearchProvider API.
        """
        results = await self.search(query, max_results=20)
        return {"query": query, "results": results, "provider": "searxng"}


class WebSearchService:
    """Universal search service with fallback chain."""

    def __init__(self, providers: list[BaseSearchProvider] | None = None) -> None:
        self._providers = providers or []

    def add_provider(self, provider: BaseSearchProvider) -> None:
        """Add a search provider.

        Args:
            provider: Provider to add.
        """
        self._providers.append(provider)
        self._providers.append(provider)

    async def query(
        self, query: str, max_results: int = 5, provider: str | None = None
    ) -> list[dict[str, Any]]:
        """Search via specified provider or fallback chain.

        Args:
            query: Search query.
            max_results: Maximum results.
            provider: Optional provider name.

        Returns:
            List of search results.

        Raises:
            ValueError: If specified provider not found.
        """
        if provider:
            for p in self._providers:
                if p.name == provider:
                    return await p.search(query, max_results)
            raise ValueError(f"Provider '{provider}' not found")

        last_error: Exception | None = None
        for p in self._providers:
            try:
                return await p.search(query, max_results)
            except Exception as exc:
                logger.warning("Search provider %s failed: %s", p.name, exc)
                last_error = exc

        if last_error:
            raise last_error
        return []

    async def deep_research(
        self, query: str, provider: str | None = None
    ) -> dict[str, Any]:
        """Perform deep research via specified provider or fallback chain.

        Args:
            query: Research query.
            provider: Optional provider name.

        Returns:
            Research results.
        """
        if provider:
            for p in self._providers:
                if p.name == provider:
                    return await p.deep_research(query)

        for p in self._providers:
            try:
                return await p.deep_research(query)
            except Exception as exc:
                logger.warning("Deep research provider %s failed: %s", p.name, exc)

        return {"query": query, "results": [], "error": "All providers failed"}


_web_search: WebSearchService | None = None


def get_web_search_service() -> WebSearchService:
    global _web_search
    if _web_search is not None:
        return _web_search

    _web_search = WebSearchService()

    try:
        from src.backend.core.config.settings import settings

        perplexity_key = getattr(settings, "perplexity_api_key", None) or ""
        tavily_key = getattr(settings, "tavily_api_key", None) or ""

        if perplexity_key:
            _web_search.add_provider(PerplexityProvider(api_key=perplexity_key))
        if tavily_key:
            _web_search.add_provider(TavilyProvider(api_key=tavily_key))
    except (ImportError, AttributeError):
        pass

    # SearXNG registration через env var (без отдельного Settings класса).
    # Включается только если SEARXNG_BASE_URL задан И feature-flag активен.
    try:
        from src.backend.core.config.features import feature_flags

        searxng_url = os.getenv("SEARXNG_BASE_URL", "").strip()
        if searxng_url and getattr(feature_flags, "search_provider_searxng", False):
            engines_env = os.getenv("SEARXNG_ENGINES", "google,bing,duckduckgo")
            engines = [e.strip() for e in engines_env.split(",") if e.strip()]
            _web_search.add_provider(
                SearXNGProvider(base_url=searxng_url, engines=engines)
            )
    except (ImportError, AttributeError):
        pass

    return _web_search
