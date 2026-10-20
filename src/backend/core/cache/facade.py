# ruff: noqa: S108 — false positive

"""S165 W1: UnifiedCacheFacade (Rule 1, Rule 6) — canonical ABC.

Cycle 167 (ADR-0352 Stage 4): concrete impls (``MemoryCacheFacade``,
``FallbackCacheFacade``, ``RedisCacheFacade``) удалены.

Canonical interface остаётся:
- ``UnifiedCacheFacade`` ABC — canonical для всего проекта.
- ``src.backend.services.cache.UnifiedCacheFacade`` — production
  implementation (extends этот ABC + namespace + capability +
  observability, см. ADR-0352 Stage 2).
- ``src.backend.core.di.providers.cache.get_cache_facade`` — dev/test
  helper (использует ``MemoryBackend`` / ``FallbackCacheFacade`` —
  внутренний, не public API).

Per Rule 1: консьюмер не должен знать о backend (Redis / Memory / Disk).
Per Rule 6: pool + healthcheck + retry fallback (Redis -> Memory при недоступности).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from pydantic import BaseModel, Field

__all__ = (
    "CacheError",
    "CacheInvalidationPolicy",
    "UnifiedCacheFacade",
)


class CacheError(Exception):
    """Базовое исключение cache-фасада."""


class CacheInvalidationPolicy(BaseModel):
    """Стратегия инвалидации кэша (Rule 12).

    S165 W1: ttl + invalidation tag + namespace strategy.
    """

    default_ttl_seconds: int = Field(default=3600, ge=1, description="TTL по умолчанию")
    max_entries: int = Field(default=10000, ge=1, description="Макс. entries")
    enable_tag_invalidation: bool = Field(
        default=True, description="Tag-based invalidation"
    )
    namespace_separator: str = Field(default=":", description="Разделитель namespace")


class UnifiedCacheFacade(ABC):
    """Абстрактный фасад cache (Rule 1).

    Canonical interface для всего проекта. Production impl:
    :class:`src.backend.services.cache.UnifiedCacheFacade` (cycle 165,
    ADR-0352 Stage 2). Dev/test helper:
    :func:`src.backend.core.di.providers.cache.get_cache_facade`.

    TTL + tag invalidation policy per CacheInvalidationPolicy.

    Cycle 167 (ADR-0352 Stage 4): этот ABC — единственное, что осталось
    от core/cache/facade. ``MemoryCacheFacade``, ``FallbackCacheFacade``,
    ``RedisCacheFacade`` удалены (были deprecated cycle 166).
    Disk-tier реализуется через
    ``src.backend.infrastructure.cache.backends.disk.DiskCacheBackend``
    (async I/O via aiofiles) и используется production runtime через
    :class:`services.cache.UnifiedCacheFacade`.
    """

    policy: ClassVar[CacheInvalidationPolicy] = CacheInvalidationPolicy()

    @abstractmethod
    async def get(self, key: str) -> bytes | None:
        """Получить значение по ключу. None если не найдено."""

    @abstractmethod
    async def set(
        self,
        key: str,
        value: bytes,
        ttl_seconds: int | None = None,
        tags: list[str] | None = None,
    ) -> None:
        """Сохранить значение с опциональным TTL + tag инвалидацией."""

    @abstractmethod
    async def delete(self, *keys: str) -> None:
        """Удалить один или несколько ключей."""

    @abstractmethod
    async def delete_by_tag(self, tag: str) -> int:
        """Удалить все ключи с тегом. Возвращает кол-во удалённых."""

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Проверить существование ключа."""

    @abstractmethod
    async def healthcheck(self) -> bool:
        """Проверить здоровье backend (Rule 6)."""