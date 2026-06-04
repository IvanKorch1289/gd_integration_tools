"""Search providers — Perplexity, Tavily, SearXNG с fallback chain."""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from typing import Any

__all__ = (
    "BaseSearchProvider",
    "PerplexityProvider",
    "SearXNGProvider",
    "TavilyProvider",
    "WebSearchService",
    "get_web_search_service",
)

logger = logging.getLogger(__name__)


class BaseSearchProvider(ABC):
    """Абстрактный поисковый провайдер."""

    name: str = "base"

    @abstractmethod
    async def search(
        self, query: str, max_results: int = 5
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def deep_research(self, query: str) -> dict[str, Any]: ...


class PerplexityProvider(BaseSearchProvider):
    """Поиск через Perplexity API."""

    name = "perplexity"

    def __init__(self, api_key: str, model: str = "sonar") -> None:
        self._api_key = api_key
        self._model = model

    async def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
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
        results = await self.search(query, max_results=10)
        return {"query": query, "results": results, "provider": self.name}


class TavilyProvider(BaseSearchProvider):
    """Поиск через Tavily API."""

    name = "tavily"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
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
    """Поиск через self-hosted SearXNG meta-search (free, unlimited).

    Согласно research-отчёту 2026-05-13 (`vault/research-2026-05-13-search-engines.md`),
    SearXNG — production-ready free кандидат: privacy-first, self-hosted,
    агрегирует Google/Bing/DuckDuckGo/Wikipedia. Подходит для банковской/air-gap
    среды без зависимости от cloud-providers.

    Args:
        base_url: URL self-hosted SearXNG instance (например, http://searxng:8080).
        engines: список engines (по умолчанию google,bing,duckduckgo).
        timeout: HTTP timeout в секундах.
    """

    name = "searxng"

    def __init__(
        self, base_url: str, engines: list[str] | None = None, timeout: float = 15.0
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._engines = engines or ["google", "bing", "duckduckgo"]
        self._timeout = timeout

    async def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
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
    """Универсальный сервис поиска с fallback chain."""

    def __init__(self, providers: list[BaseSearchProvider] | None = None) -> None:
        self._providers = providers or []

    def add_provider(self, provider: BaseSearchProvider) -> None:
        self._providers.append(provider)

    async def query(
        self, query: str, max_results: int = 5, provider: str | None = None
    ) -> list[dict[str, Any]]:
        """Поиск через указанный провайдер или fallback chain."""
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
