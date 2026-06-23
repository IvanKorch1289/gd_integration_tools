"""Утилиты ядра общего назначения.

Содержит:

- ``async_helpers`` — async-итераторы (``AsyncChunkIterator``);
- ``async_utils`` — asyncer-обёртки (``run_sync_in_thread``,
  ``gather_with_timeout``, ``async_with_timeout``);
- ``cache_keys`` — детерминированные ключи кэша;
- ``circuit_breaker`` — простейший circuit-breaker (исторический модуль);
- ``datetime_utils`` — pendulum/stdlib datetime хелперы (S57 W1);
- ``json_utils`` — orjson-based JSON serialization;
- ``metrics_registry`` — idempotent Prometheus factory;
- ``redis_fallback`` — Redis → TTLCache fallback;
- ``route_timeout`` — ``RouteTimeoutSpec`` frozen dataclass;
- ``task_registry`` — централизованный реестр фоновых ``asyncio.Task``
  (V15 R-V15-11);
- ``watchdog`` — deadline-эскалация для long-running async-задач.

S5 fix (S36-W11): модули ``datetime_utils`` и ``json_utils`` мигрированы
из удалённого ``core/util/`` пакета. Ранее сосуществовали ``core/util/``
(2 файла) + ``core/utils/`` (8 файлов) — комментарий ``__init__.py`` даже
ссылался на несуществующий ``circuit_breaker`` (S95 W4 dead reference).
"""

from src.backend.core.utils.async_helpers import AsyncChunkIterator
from src.backend.core.utils.async_utils import (
    async_with_timeout,
    gather_with_timeout,
    run_sync_in_thread,
)
from src.backend.core.utils.cache_keys import build_cache_key
from src.backend.core.utils.datetime_utils import (
    ensure_utc,
    humanize_delta,
    parse_dt,
    utc_now,
)
from src.backend.core.utils.json_utils import dumps_bytes, dumps_str, loads
from src.backend.core.utils.metrics_registry import MetricsRegistry, metrics_registry
from src.backend.core.utils.redis_fallback import (
    FallbackCache,
    RedisErrorCategory,
    RedisLike,
)
from src.backend.core.utils.route_timeout import RouteTimeoutSpec
from src.backend.core.utils.task_registry import (
    TaskRegistry,
    get_task_registry,
    reset_task_registry,
)
from src.backend.core.utils.watchdog import Watchdog

__all__ = (
    "AsyncChunkIterator",
    "FallbackCache",
    "MetricsRegistry",
    "RedisErrorCategory",
    "RedisLike",
    "RouteTimeoutSpec",
    "TaskRegistry",
    "Watchdog",
    "async_with_timeout",
    "build_cache_key",
    "dumps_bytes",
    "dumps_str",
    "ensure_utc",
    "gather_with_timeout",
    "get_task_registry",
    "humanize_delta",
    "loads",
    "metrics_registry",
    "parse_dt",
    "reset_task_registry",
    "run_sync_in_thread",
    "utc_now",
)
