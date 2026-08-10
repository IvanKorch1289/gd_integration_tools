"""Cache backends (Wave 2.2).

Поддерживаемые бэкенды реализуют ABC :class:`core.interfaces.CacheBackend`:

* :class:`MemoryBackend` — in-process ``cachetools.TTLCache`` (тесты, dev);
* :class:`RedisBackend` — стандартный Redis client (asyncio);
* :class:`KeyDBBackend` — drop-in для Redis (тот же RESP, multi-threaded);
* :class:`MemcachedBackend` — опциональный, требует ``aiomcache`` (Wave 2.2+).

Сборка через :func:`create_cache_backend` (см. ``factory.py``).
"""

from src.backend.infrastructure.cache.backends.disk import (
    DiskCacheBackend,  # noqa: F401 — re-export
)
from src.backend.infrastructure.cache.backends.keydb import (
    KeyDBBackend,  # noqa: F401 — re-export
)
from src.backend.infrastructure.cache.backends.memory import (
    MemoryBackend,  # noqa: F401 — re-export
)
from src.backend.infrastructure.cache.backends.redis import (
    RedisBackend,  # noqa: F401 — re-export
)

__all__ = ("DiskCacheBackend", "KeyDBBackend", "MemoryBackend", "RedisBackend")
