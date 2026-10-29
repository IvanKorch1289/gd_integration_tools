"""Cycle 168 tests: log throttling в ``UnifiedCacheFacade``.

PROD_READINESS_LOGGING_CACHE_2026-10-20 §3: при недоступности primary (Redis)
каждое обращение к кэшу логировало WARNING → log-spam (5000 warnings/s) →
backpressure в batching_router → потеря логов.

Cycle 168: throttling через ``_LOG_THROTTLE_WINDOW_SECONDS = 60s``.
Первый warning за window — WARNING с описанием; последующие — DEBUG.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import pytest

from src.backend.core.interfaces.cache import CacheBackend
from src.backend.infrastructure.cache.backends.memory import MemoryBackend
from src.backend.services.cache.facade import UnifiedCacheFacade, _log_throttle_counters


class FailingBackend(CacheBackend):
    """Backend, который всегда падает на всех операциях."""

    def __init__(self, error: str = "down") -> None:
        self.error = error

    async def get(self, key: str) -> bytes | None:
        raise RuntimeError(self.error)

    async def set(self, key: str, value: bytes, ttl: int | None = None) -> None:
        raise RuntimeError(self.error)

    async def delete(self, *keys: str) -> None:
        raise RuntimeError(self.error)

    async def delete_pattern(self, pattern: str) -> None:
        raise RuntimeError(self.error)

    async def exists(self, key: str) -> bool:
        raise RuntimeError(self.error)


class CountingHandler(logging.Handler):
    """Handler, который считает WARNING/DEBUG emissions."""

    def __init__(self) -> None:
        super().__init__()
        self.warnings: list[str] = []
        self.debugs: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno == logging.WARNING:
            self.warnings.append(record.getMessage())
        elif record.levelno == logging.DEBUG:
            self.debugs.append(record.getMessage())


@pytest.fixture
async def counter() -> AsyncIterator[CountingHandler]:
    """Yield CountingHandler, подключённый к ``services.cache.facade`` logger."""
    handler = CountingHandler()
    handler.setLevel(logging.DEBUG)
    logger = logging.getLogger("services.cache.facade")
    original_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(original_level)
        _log_throttle_counters.clear()


@pytest.fixture(autouse=True)
def _reset_throttle_counters() -> None:
    """Сбрасывает ``_log_throttle_counters`` перед каждым тестом.

    Cycle 168: counter — module-level ``defaultdict``; другие тесты в suite
    могут наполнить его до запуска этих тестов. autouse гарантирует чистый
    state для каждого теста.
    """
    _log_throttle_counters.clear()


class TestLogThrottling:
    async def test_first_failure_logs_warning(
        self, counter: CountingHandler
    ) -> None:
        """Первое падение за window = WARNING с описанием."""
        facade = UnifiedCacheFacade(
            primary=FailingBackend(),
            memory_fallback=MemoryBackend(maxsize=10),
        )
        await facade.get_ns("k1")
        assert len(counter.warnings) == 1
        assert "Cache primary get failed" in counter.warnings[0]
        assert "suppressing repeats" in counter.warnings[0]

    async def test_subsequent_failures_throttled(
        self, counter: CountingHandler
    ) -> None:
        """50 последующих failures = 1 short summary + остальные DEBUG."""
        facade = UnifiedCacheFacade(
            primary=FailingBackend(),
            memory_fallback=MemoryBackend(maxsize=10),
        )
        for i in range(50):
            await facade.get_ns(f"k{i}")
        # 1 initial warning + 1 summary = 2 warnings
        # Остальные — DEBUG (suppressed)
        assert len(counter.warnings) == 2
        assert len(counter.debugs) >= 48

    async def test_throttle_counter_increments(
        self, counter: CountingHandler
    ) -> None:
        """Counter растёт с каждым suppressed failure."""
        facade = UnifiedCacheFacade(
            primary=FailingBackend(),
            memory_fallback=MemoryBackend(maxsize=10),
        )
        for i in range(10):
            await facade.get_ns(f"k{i}")
        # Counter "primary.get" должен быть 10
        assert "primary.get" in _log_throttle_counters
        _, count = _log_throttle_counters["primary.get"]
        assert count == 10

    async def test_different_backends_throttled_independently(
        self, counter: CountingHandler
    ) -> None:
        """primary и memory используют разные throttle buckets."""
        facade = UnifiedCacheFacade(
            primary=FailingBackend("primary_down"),
            memory_fallback=FailingBackend("memory_down"),
            disk_fallback=None,
        )
        await facade.get_ns("k1")
        # Первое падение primary → 1 warning
        # Затем memory fail → 1 warning (другой bucket)
        assert len(counter.warnings) >= 2
        assert any("primary" in w for w in counter.warnings)
        assert any("memory" in w for w in counter.warnings)

    async def test_log_throttle_returns_hit_from_fallback(
        self, counter: CountingHandler
    ) -> None:
        """Throttling не блокирует fallback path — value возвращается."""
        from src.backend.services.cache.facade import CacheResult

        memory = MemoryBackend(maxsize=10)
        facade = UnifiedCacheFacade(
            primary=FailingBackend(),
            memory_fallback=memory,
        )
        # Pre-populate memory with the namespaced key (facade prefixes with
        # ``namespace:key``).
        await memory.set("default:k1", b"value_from_memory")
        result = await facade.get_ns("k1")
        assert isinstance(result, CacheResult)
        assert result.value == b"value_from_memory"
        assert result.backend == "memory"
