"""Round 21+22: autouse fixtures для сброса state между DSL-тестами.

Зеркало :mod:`tests.unit.services.ai.conftest` (Sprint 3 improvement #5)
расширенное с Round 22:
1. AIGateway composition root reset (``_overrides``, ``lru_cache``).
2. Svcs registry reset (``clear_registry()``) — закрывает
   test_react_isolated_uses_sandbox regression от test_agent_graph_tool_policy,
   который вызывает ``clear_registry()`` без proper teardown.

Без этих fixtures DSL тесты получают silent pollution от предыдущих
тестов → test ordering failures.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_ai_gateway_singleton_for_dsl() -> None:
    """Сбрасывает AIGateway composition root между DSL-тестами."""
    from src.backend.core.di.providers.ai import (
        _build_ai_gateway_singleton,
        _overrides,
    )

    _overrides.pop("ai_gateway", None)
    _build_ai_gateway_singleton.cache_clear()
    yield
    _overrides.pop("ai_gateway", None)
    _build_ai_gateway_singleton.cache_clear()


@pytest.fixture(autouse=True)
def _reset_svcs_registry_for_dsl() -> None:
    """Round 22: clear svcs registry между DSL-тестами.

    ``test_agent_graph_tool_policy.py`` вызывает ``clear_registry()``
    внутри test bodies без proper teardown — следующий тест в
    алфавитном порядке видит пустой registry и fails.
    """
    from src.backend.core.svcs_registry import clear_registry

    clear_registry()
    yield
    clear_registry()

