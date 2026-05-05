"""KeyDBBackend — drop-in для Redis на том же RESP-протоколе (Wave 2.2).

KeyDB полностью совместим с Redis на уровне протокола, поэтому
``redis.asyncio`` отлично работает против KeyDB-сервера. Этот класс
наследуется от :class:`RedisBackend` и существует ради ясной семантики
конфигурации (``CACHE_BACKEND=keydb``) и места для KeyDB-специфичных
расширений (active-active, MULTI-EXEC и т.п.).
"""

from __future__ import annotations

from src.infrastructure.cache.backends.redis import RedisBackend

__all__ = ("KeyDBBackend",)


class KeyDBBackend(RedisBackend):
    """KeyDB-бэкенд (RESP-совместимый, многопоточный)."""

    def __init__(self, client, *, active_replica: bool = False) -> None:
        super().__init__(client=client)
        self._active_replica = active_replica
