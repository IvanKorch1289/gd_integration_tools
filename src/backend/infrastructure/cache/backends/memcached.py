"""MemcachedBackend на ``aiomcache`` (Wave 8.4 — stub).

Реализует :class:`core.interfaces.CacheBackend` через ``aiomcache.Client``.
Зависимость ``aiomcache`` опциональная — если она не установлена,
конструктор бросает ``RuntimeError`` с понятным сообщением. Этот же
паттерн используется в Mongo cert-store backend (Wave 8.4).

Memcached не поддерживает pattern-удаление (нет KEYS/SCAN), поэтому
``delete_pattern`` логирует warning и завершает no-op. Для production
лучше использовать Redis/KeyDB.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.backend.core.interfaces.cache import CacheBackend

if TYPE_CHECKING:  # pragma: no cover
    import aiomcache

__all__ = ("MemcachedBackend",)

_logger = logging.getLogger(__name__)


class MemcachedBackend(CacheBackend):
    """Реализация ``CacheBackend`` поверх ``aiomcache``.

    Args:
        host: Хост Memcached (по умолчанию ``127.0.0.1``).
        port: Порт Memcached (по умолчанию ``11211``).
        default_ttl: TTL по умолчанию в секундах.

    Raises:
        RuntimeError: Если пакет ``aiomcache`` не установлен.
    """

    def __init__(
        self, host: str = "127.0.0.1", port: int = 11211, *, default_ttl: int = 3600
    ) -> None:
        try:
            import aiomcache
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "Memcached-бэкенд требует пакет 'aiomcache'. "
                "Добавьте его в pyproject.toml и переинициализируйте."
            ) from exc

        self._aiomcache = aiomcache
        self._client: aiomcache.Client = aiomcache.Client(host=host, port=port)
        self._default_ttl = default_ttl

    @staticmethod
    def _to_bytes(key: str) -> bytes:
        return key.encode("utf-8")

    async def get(self, key: str) -> bytes | None:
        return await self._client.get(self._to_bytes(key))

    async def set(self, key: str, value: bytes, ttl: int | None = None) -> None:
        await self._client.set(
            self._to_bytes(key),
            value,
            exptime=ttl if ttl is not None else self._default_ttl,
        )

    async def delete(self, *keys: str) -> None:
        for key in keys:
            await self._client.delete(self._to_bytes(key))

    async def delete_pattern(self, pattern: str) -> None:  # noqa: ARG002
        _logger.warning(
            "memcached: delete_pattern не поддерживается (нет KEYS/SCAN), no-op"
        )

    async def exists(self, key: str) -> bool:
        return (await self._client.get(self._to_bytes(key))) is not None

    async def close(self) -> Any:
        return await self._client.close()
