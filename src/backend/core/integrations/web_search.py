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

from src.backend.core.di.providers.infrastructure_facade import (  # noqa: E402,F401
    get_base_search_provider_class as _get_bsp_cls,
    get_perplexity_provider_class as _get_pp_cls,
    get_searxng_provider_class as _get_sxp_cls,
    get_tavily_provider_class as _get_tp_cls,
    get_web_search_service_class as _get_wss_cls,
    get_web_search_service_factory as _get_wss_fn,
)
BaseSearchProvider = _get_bsp_cls()
PerplexityProvider = _get_pp_cls()
SearXNGProvider = _get_sxp_cls()
TavilyProvider = _get_tp_cls()
WebSearchService = _get_wss_cls()
get_web_search_service = _get_wss_fn()

__all__ = (
    "BaseSearchProvider",
    "PerplexityProvider",
    "SearXNGProvider",
    "TavilyProvider",
    "WebSearchService",
    "get_web_search_service",
)
