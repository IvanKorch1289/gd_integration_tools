"""Утилиты ядра общего назначения.

Содержит:

- ``async_helpers`` — async iterator (``async_chunk_iterator``);
- ``cache_keys`` — детерминированные ключи кэша;
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
(2 файла) + ``core/utils/`` (8 файлов).
"""

from src.backend.core.utils.async_helpers import async_chunk_iterator
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

from src.backend.core.utils.async_utils import (
    gather_with_timeout,
    safe_gather,
    run_sync_in_thread,
)

__all__ = (
    "gather_with_timeout",
    "safe_gather",
    "run_sync_in_thread",
    "build_cache_key",
    "load_json",
    "dump_json",
    "now_utc",
    "async_chunk_iterator",
    "FallbackCache",
    "MetricsRegistry",
    "RedisErrorCategory",
    "RedisLike",
    "RouteTimeoutSpec",
    "TaskRegistry",
    "Watchdog",
    "get_task_registry",
    "humanize_delta",
    "loads",
    "metrics_registry",
    "parse_dt",
    "reset_task_registry",
    "utc_now",
)
