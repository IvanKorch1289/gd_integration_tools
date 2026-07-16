"""Auto-reset circuit breaker registry between tests (S3 Wave).

BreakerRegistry — module-singleton (``lru_cache(maxsize=1)`` в
``core/resilience/breaker.py``). Состояние breaker'ов переживает
тесты: один ``send_5xx`` открывает ``http_sink``, и все последующие
тесты в suite падают на ``CircuitOpen``. Чтобы ``@with_breaker``
не ломал существующие unit-тесты sinks/sources, перед каждым
тестом чистим реестр.

Покрывает ``tests/unit/infrastructure/sinks/`` и
``tests/unit/infrastructure/sources/`` — фикстура ``autouse=True``
применяется ко всем тестам в этих поддеревьях.

Production код не вызывает ``reset()`` — он нужен только в test scope.
"""

from __future__ import annotations

import pytest

from src.backend.core.resilience.breaker import get_breaker_registry


@pytest.fixture(autouse=True)
def _reset_breakers() -> None:
    """Чистит глобальный ``BreakerRegistry`` перед каждым тестом."""
    get_breaker_registry().reset()
    yield
