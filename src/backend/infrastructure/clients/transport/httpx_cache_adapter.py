"""Адаптер кэширования для httpx через Hishel (RFC 7234).

K2 Sprint 7 — httpx unified transport stack. Реализует ленивый импорт
``hishel`` (cache transport over httpx); при отсутствии пакета возвращает
``None`` — caller должен gracefully fallback на чистый httpx.

Особенности:
* RFC 7234 HTTP-caching (Cache-Control, Vary, ETag, conditional GET).
* ``Controller(allow_heuristics=True)`` — эвристики для ответов без Cache-Control.
* ``FileStorage`` по умолчанию (cache_dir конфигурируется через settings).
* Lazy-import: ``hishel`` не входит в обязательные зависимости — её отсутствие
  не должно ломать существующий HttpxClient.

См. также:
* ADR S7-K2 (Unified httpx transport stack).
* feature_flag ``httpx_unified_transport`` (default-OFF).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger("transport.httpx.cache")

__all__ = (
    "build_cache_transport",
    "is_hishel_available",
)


def is_hishel_available() -> bool:
    """Проверяет доступность пакета ``hishel`` (lazy-import friendly).

    Returns:
        ``True`` если ``hishel`` импортируется без ошибок.
    """
    try:
        import hishel  # noqa: F401

        return True
    except ImportError:
        return False


def build_cache_transport(
    inner_transport: httpx.AsyncBaseTransport,
    *,
    cache_dir: str | Path | None = None,
    allow_heuristics: bool = True,
    allow_stale: bool = False,
    cacheable_methods: tuple[str, ...] = ("GET", "HEAD"),
    cacheable_status_codes: tuple[int, ...] = (200, 203, 300, 301, 308),
) -> httpx.AsyncBaseTransport | None:
    """Оборачивает inner transport в Hishel CacheTransport.

    Args:
        inner_transport: Базовый async transport (RetryTransport или HTTPTransport).
        cache_dir: Директория для FileStorage (если ``None`` — system temp).
        allow_heuristics: Разрешить эвристические сроки жизни для ответов без
            явного Cache-Control (RFC 7234 §4.2.2).
        allow_stale: Разрешить отдачу stale-ответов при сетевой ошибке.
        cacheable_methods: HTTP-методы, кэшируемые транспортом.
        cacheable_status_codes: HTTP-статусы, кэшируемые транспортом.

    Returns:
        ``hishel.AsyncCacheTransport`` если пакет установлен, иначе ``None``.

    Note:
        При ``None`` caller должен использовать ``inner_transport`` напрямую —
        graceful fallback на чистый httpx без cache.
    """
    try:
        import hishel
    except ImportError:
        logger.debug("hishel недоступен — cache transport не активирован")
        return None

    storage_kwargs: dict[str, Any] = {}
    if cache_dir is not None:
        storage_kwargs["base_path"] = Path(cache_dir)
    storage = hishel.AsyncFileStorage(**storage_kwargs)

    controller = hishel.Controller(
        cacheable_methods=list(cacheable_methods),
        cacheable_status_codes=list(cacheable_status_codes),
        allow_heuristics=allow_heuristics,
        allow_stale=allow_stale,
    )

    return hishel.AsyncCacheTransport(
        transport=inner_transport,
        storage=storage,
        controller=controller,
    )
