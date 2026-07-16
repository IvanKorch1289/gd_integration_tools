"""Search providers bridge — lazy accessors for ``clients.external.search_providers``.

Extracted from the monolithic ``infrastructure_facade.py`` (S171 decomp).
Each accessor performs a lazy import so that infrastructure modules are
not loaded until first call, preserving import-time isolation (D102).

Covers:
    * ``WebSearchService`` class + factory
    * concrete providers: ``TavilyProvider``, ``SearXNGProvider``,
      ``PerplexityProvider``
    * ``BaseSearchProvider`` base class
    * full ``search_providers`` module
"""

from __future__ import annotations

from typing import Any

__all__ = (
    "get_search_providers_module",
    "get_base_search_provider_class",
    "get_perplexity_provider_class",
    "get_searxng_provider_class",
    "get_tavily_provider_class",
    "get_web_search_service_class",
    "get_web_search_service_factory",
)


def get_search_providers_module() -> Any:
    """Возвращает ``clients.external.search_providers`` module."""
    from src.backend.infrastructure.clients.external import search_providers
    return search_providers


def get_base_search_provider_class() -> Any:
    """Возвращает ``clients.external.search_providers.BaseSearchProvider`` class."""
    from src.backend.infrastructure.clients.external.search_providers import BaseSearchProvider

    return BaseSearchProvider


def get_perplexity_provider_class() -> Any:
    """Возвращает ``clients.external.search_providers.PerplexityProvider`` class."""
    from src.backend.infrastructure.clients.external.search_providers import PerplexityProvider

    return PerplexityProvider


def get_searxng_provider_class() -> Any:
    """Возвращает ``clients.external.search_providers.SearXNGProvider`` class."""
    from src.backend.infrastructure.clients.external.search_providers import SearXNGProvider

    return SearXNGProvider


def get_tavily_provider_class() -> Any:
    """Возвращает ``clients.external.search_providers.TavilyProvider`` class."""
    from src.backend.infrastructure.clients.external.search_providers import TavilyProvider

    return TavilyProvider


def get_web_search_service_class() -> Any:
    """Возвращает ``clients.external.search_providers.WebSearchService`` class."""
    from src.backend.infrastructure.clients.external.search_providers import WebSearchService

    return WebSearchService


def get_web_search_service_factory() -> Any:
    """Возвращает ``clients.external.search_providers.get_web_search_service`` factory."""
    from src.backend.infrastructure.clients.external.search_providers import get_web_search_service
    return get_web_search_service
