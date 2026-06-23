"""Capability-checked facade для web search providers (S44 W1).

ADR-0248 follow-up: ``extensions/osint_agent/functions/osint_workflow.py``
импортирует ``get_web_search_service`` из
``infrastructure.clients.external.search_providers``. Это нарушает V22 invariant
(extensions → only core + capability-checked facades).

Single-entry facade здесь позволяет extensions импортировать через core без
layer-linter violation. См. layer-linter exception для
``core/integrations/web_search.py → infrastructure.clients.external.search_providers``.

S44 W1 sprint goal: закрыть 2 extensions violations (Q1 sprint 43 audit catch).
"""

from __future__ import annotations

from src.backend.infrastructure.clients.external.search_providers import (  # noqa: E402,F401
    BaseSearchProvider,
    PerplexityProvider,
    SearXNGProvider,
    TavilyProvider,
    WebSearchService,
    get_web_search_service,
)

__all__ = (
    "BaseSearchProvider",
    "PerplexityProvider",
    "SearXNGProvider",
    "TavilyProvider",
    "WebSearchService",
    "get_web_search_service",
)
