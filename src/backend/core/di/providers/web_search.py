"""Web search domain provider — S170 NEW (Milestone 1).

Single entry point для web search providers (searxng/google/etc.).

Usage::

    from src.backend.core.di.providers.web_search import get_web_search_provider

    search = get_web_search_provider()
    results = await search.search(query="...", top_k=10)
"""

from __future__ import annotations

from typing import Any

from src.backend.core.di.module_registry import resolve_module

_overrides: dict[str, Any] = {}


def get_web_search_provider() -> Any:
    """Вернуть singleton WebSearch provider."""
    if "web_search" in _overrides:
        return _overrides["web_search"]
    return resolve_module("infrastructure.clients.external.search_providers").get_default()


def set_web_search_provider(search: Any) -> None:
    """Test-инжекция web search provider."""
    _overrides["web_search"] = search


__all__ = ("get_web_search_provider", "set_web_search_provider")
