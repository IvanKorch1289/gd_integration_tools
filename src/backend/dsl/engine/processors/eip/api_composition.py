"""API Composition Processor — BFF pattern для composing multiple APIs (v21 §7.3).

Extends ScatterGather pattern с API-specific features:
* HTTP call configs (URL/method/headers/body) per source
* Per-source transform (sync/async callable)
* Per-source TTL cache
* Per-source fallback value (on error/timeout)
* Merge strategies: merge_dicts, list, custom merger

Use cases (BFF pattern):
* Mobile-optimized API: aggregate user + orders + notifications → 1 response
* Admin dashboard: fetch metrics + alerts + recent activity → 1 page
* Public API: compose search + recommendations + ads → 1 query response

Usage::

    composition = APICompositionProcessor(
        sources=[
            APISource(
                name="user",
                url="https://api.example.com/users/{user_id}",
                method="GET",
                path_params={"user_id": "u-1"},
                transform_fn=lambda r: {"user": r},
            ),
            APISource(
                name="orders",
                url="https://api.example.com/orders?user={user_id}",
                method="GET",
                path_params={"user_id": "u-1"},
                transform_fn=lambda r: {"orders": r.get("items", [])},
                cache_ttl_seconds=60,
            ),
            APISource(
                name="notifications",
                url="https://api.example.com/notifications",
                method="GET",
                transform_fn=lambda r: {"notifications": r},
                fallback_value={"notifications": []},  # graceful degradation
            ),
        ],
        merge_strategy="merge_dicts",
        timeout_seconds=5.0,
    )
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = (
    "APICompositionProcessor",
    "APICompositionMixin",
    "APISource",
    "CacheStore",
    "HTTPFetcher",
    "InMemoryCacheStore",
    "MergeStrategy",
)

_log = logging.getLogger(__name__)


# ── HTTP fetcher (DI-friendly) ────────────────────────────────────────


HTTPFetcher = Callable[[str, str, dict[str, str], Any, float], Awaitable[Any]]


def _default_http_fetcher() -> HTTPFetcher:
    """Lazy HTTP fetcher provider — imports только на actual call, не at __init__."""

    async def fetcher(
        url: str, method: str, headers: dict[str, str], body: Any, timeout: float
    ) -> Any:
        from src.backend.infrastructure.external_apis.http_client import get_http_client

        client = get_http_client()
        return await client.request(
            method=method, url=url, headers=headers, json_body=body, timeout=timeout
        )

    return fetcher


# ── Cache store (DI-friendly) ──────────────────────────────────────────


class InMemoryCacheStore:
    """In-memory TTL cache для API composition (per-process, thread-safe)."""

    def __init__(self) -> None:
        import threading

        self._cache: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        import time as _t

        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if _t.time() > expires_at:
                del self._cache[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        with self._lock:
            self._cache[key] = (time.time() + ttl_seconds, value)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()


# Module singleton
_cache: InMemoryCacheStore | None = None


def get_cache_store() -> InMemoryCacheStore:
    global _cache
    if _cache is None:
        _cache = InMemoryCacheStore()
    return _cache


def reset_cache_store() -> InMemoryCacheStore:
    global _cache
    _cache = InMemoryCacheStore()
    return _cache


CacheStore = InMemoryCacheStore  # type alias for DI


# ── APISource (config per source) ──────────────────────────────────────


class MergeStrategy(str, Enum):
    """Как merge результаты от sources в unified response."""

    MERGE_DICTS = "merge_dicts"  # dict.update() всех results
    LIST = "list"  # list of all results
    CUSTOM = "custom"  # custom_merger(results: list) -> result


@dataclass(frozen=True, slots=True)
class APISource:
    """Один API endpoint для composition.

    Attributes:
        name: Уникальный ID source (используется как ключ в results).
        url: URL endpoint (с optional path params: ``{user_id}``).
        method: HTTP method (GET, POST, etc.). Default GET.
        headers: HTTP headers (auth tokens, content-type, ...).
        body: Request body (для POST/PUT/PATCH).
        path_params: Path params для URL template substitution.
        query_params: Query string params.
        transform_fn: ``(response: Any) -> Any`` — post-process response.
        fallback_value: Возвращается при error/timeout вместо raising.
        cache_ttl_seconds: TTL для in-memory cache. 0 = no cache.
    """

    name: str
    url: str
    method: str = "GET"
    headers: dict[str, str] = field(default_factory=dict)
    body: Any = None
    path_params: dict[str, Any] = field(default_factory=dict)
    query_params: dict[str, Any] = field(default_factory=dict)
    transform_fn: Callable[[Any], Any] | None = None
    fallback_value: Any = None
    cache_ttl_seconds: float = 0.0

    def render_url(self) -> str:
        """Apply path_params к URL template."""
        if not self.path_params:
            return self.url
        return self.url.format(**self.path_params)


# ── APICompositionProcessor ───────────────────────────────────────────


class APICompositionProcessor(BaseProcessor):
    """Compose multiple API endpoints → unified response (BFF pattern).

    Шаги:
    1. Для каждой source: check cache → fetch (if miss) → transform → cache
    2. Async gather всех sources (parallel)
    3. Handle per-source errors (fallback_value или record error)
    4. Merge results per strategy
    5. Store в exchange.properties + set out
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = False

    def __init__(
        self,
        sources: list[APISource],
        *,
        merge_strategy: MergeStrategy | str = MergeStrategy.MERGE_DICTS,
        custom_merger: Callable[[dict[str, Any]], Any] | None = None,
        timeout_seconds: float = 30.0,
        http_fetcher: HTTPFetcher | None = None,
        cache_store: InMemoryCacheStore | None = None,
        name: str | None = None,
    ) -> None:
        if not sources:
            raise ValueError("sources не может быть пустым")
        seen: set[str] = set()
        for s in sources:
            if s.name in seen:
                raise ValueError(f"duplicate source name {s.name!r}")
            seen.add(s.name)
        if isinstance(merge_strategy, str):
            merge_strategy = MergeStrategy(merge_strategy)
        if merge_strategy == MergeStrategy.CUSTOM and custom_merger is None:
            raise ValueError("custom_merger обязателен для MergeStrategy.CUSTOM")
        super().__init__(name=name or f"api_composition({len(sources)})")
        self._sources = list(sources)
        self._merge_strategy = merge_strategy
        self._custom_merger = custom_merger
        self._timeout = timeout_seconds
        self._fetcher: HTTPFetcher = http_fetcher or _default_http_fetcher()
        self._cache = cache_store or get_cache_store()

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        tasks = [self._fetch_source(s) for s in self._sources]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        results: dict[str, Any] = {}
        errors: dict[str, str] = {}
        for source, item in zip(self._sources, raw_results, strict=True):
            if isinstance(item, BaseException):
                if source.fallback_value is not None:
                    results[source.name] = (
                        source.transform_fn(source.fallback_value)
                        if source.transform_fn
                        else source.fallback_value
                    )
                    errors[source.name] = f"fallback: {item!r}"
                else:
                    errors[source.name] = str(item)
            else:
                results[source.name] = item

        # If any source failed without fallback → fail exchange
        failed_sources = [
            s.name
            for s in self._sources
            if s.name in errors and s.fallback_value is None
        ]
        if failed_sources:
            exchange.fail(
                f"API composition failed for sources: {failed_sources}, "
                f"errors: {errors}"
            )

        # Merge per strategy
        if self._merge_strategy == MergeStrategy.MERGE_DICTS:
            merged: dict[str, Any] = {}
            for v in results.values():
                if isinstance(v, dict):
                    merged.update(v)
                else:
                    merged.setdefault("_items", []).append(v)
            final = merged
        elif self._merge_strategy == MergeStrategy.LIST:
            final = list(results.values())
        elif self._merge_strategy == MergeStrategy.CUSTOM:
            assert self._custom_merger is not None
            final = self._custom_merger(results)
        else:
            final = results

        exchange.set_property("composition_results", results)
        if errors:
            exchange.set_property("composition_errors", errors)
        exchange.set_out(body=final, headers=dict(exchange.in_message.headers))

    async def _fetch_source(self, source: APISource) -> Any:
        """Fetch single source: cache check → HTTP → transform → cache."""
        url = source.render_url()
        cache_key = f"{source.method}:{url}"
        if source.cache_ttl_seconds > 0:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

        # Compute per-source timeout (overall / num_sources, min 1.0s)
        per_source_timeout = max(self._timeout / max(len(self._sources), 1), 1.0)

        # Add query params
        if source.query_params:
            sep = "&" if "?" in url else "?"
            query = "&".join(f"{k}={v}" for k, v in source.query_params.items())
            url = f"{url}{sep}{query}"

        response = await self._fetcher(
            url, source.method, source.headers, source.body, per_source_timeout
        )

        # Transform
        if source.transform_fn:
            response = source.transform_fn(response)

        # Cache (only if no error/exception)
        if source.cache_ttl_seconds > 0:
            self._cache.set(cache_key, response, source.cache_ttl_seconds)

        return response


class APICompositionMixin:
    """Mixin для :class:`RouteBuilder` — chainable ``.api_composition(...)``."""

    __slots__ = ()

    def api_composition(
        self,
        sources: list[APISource],
        *,
        merge_strategy: MergeStrategy | str = MergeStrategy.MERGE_DICTS,
        custom_merger: Callable[[dict[str, Any]], Any] | None = None,
        timeout_seconds: float = 30.0,
    ) -> "RouteBuilder":
        """Добавить :class:`APICompositionProcessor` в pipeline.

        Args:
            sources: List of :class:`APISource` configs.
            merge_strategy: MERGE_DICTS / LIST / CUSTOM.
            custom_merger: Required if merge_strategy=CUSTOM.
            timeout_seconds: Overall timeout (per-source = total / N).
        """
        return self._add(  # type: ignore[attr-defined]
            APICompositionProcessor(
                sources=sources,
                merge_strategy=merge_strategy,
                custom_merger=custom_merger,
                timeout_seconds=timeout_seconds,
            )
        )
