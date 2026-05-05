"""Cache backends (Wave 2.2).

Поддерживаемые бэкенды реализуют ABC :class:`core.interfaces.CacheBackend`:

* :class:`MemoryBackend` — in-process ``cachetools.TTLCache`` (тесты, dev);
* :class:`RedisBackend` — стандартный Redis client (asyncio);
* :class:`KeyDBBackend` — drop-in для Redis (тот же RESP, multi-threaded);
* :class:`MemcachedBackend` — опциональный, требует ``aiomcache`` (Wave 2.2+).

Сборка через :func:`create_cache_backend` (см. ``factory.py``).
"""

from src.backend.infrastructure.cache.backends.keydb import KeyDBBackend
from src.backend.infrastructure.cache.backends.memory import MemoryBackend
from src.backend.infrastructure.cache.backends.redis import RedisBackend

__all__ = ("MemoryBackend", "RedisBackend", "KeyDBBackend")
