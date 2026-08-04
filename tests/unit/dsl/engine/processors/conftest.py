"""Round 21: autouse fixture для сброса AIGateway composition root в DSL tests.

Зеркало :mod:`tests.unit.services.ai.conftest` (Sprint 3 improvement #5).
Без этого fixture DSL тесты, использующие ``get_ai_gateway()``,
получают stale gateway из предыдущего теста (silent pollution) →
test ordering failures (e.g. test_react_isolated_uses_sandbox,
test_gateway_enforce_uses_aigateway).

Покрывает:
- ``get_ai_gateway_provider()`` override (``_overrides["ai_gateway"]``)
- ``_build_ai_gateway_singleton`` ``@lru_cache(maxsize=1)``
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_ai_gateway_singleton_for_dsl() -> None:
    """Сбрасывает AIGateway composition root между DSL-тестами.

    Запускается автоматически для каждого теста в этой директории
    и под-директориях (autouse + scope по умолчанию = function).
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
