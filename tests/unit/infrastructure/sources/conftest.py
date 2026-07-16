"""Auto-reset circuit breaker registry between tests (S3 Wave).

См. ``tests/unit/infrastructure/sinks/conftest.py`` для обоснования.
"""

from __future__ import annotations

import pytest

from src.backend.core.resilience.breaker import get_breaker_registry


@pytest.fixture(autouse=True)
def _reset_breakers() -> None:
    """Чистит глобальный ``BreakerRegistry`` перед каждым тестом."""
    get_breaker_registry().reset()
    yield
