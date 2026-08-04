"""Sprint 3 improvement #5: autouse fixture для AIGateway composition root.

Удаляет boilerplate ``_overrides.pop + cache_clear`` в 4+ тестах
(``test_sprint1_3_ai_gateway_composition.py``,
``test_aigateway_capability_wiring.py``).

Без этого fixture новые тесты, забывшие ``cache_clear()``,
получат stale gateway из предыдущего теста (silent pollution).
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_ai_gateway_singleton() -> None:
    """Сбрасывает AIGateway composition root между тестами.

    Sprint 3 (improvement #5). Покрывает:
    - ``get_ai_gateway_provider()`` override (``_overrides["ai_gateway"]``)
    - ``_build_ai_gateway_singleton`` ``@lru_cache(maxsize=1)``
    """
    from src.backend.core.di.providers.ai import (
        _build_ai_gateway_singleton,
        _overrides,
    )

    _overrides.pop("ai_gateway", None)
    _build_ai_gateway_singleton.cache_clear()
    yield
    _overrides.pop("ai_gateway", None)
    _build_ai_gateway_singleton.cache_clear()
