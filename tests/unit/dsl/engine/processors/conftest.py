"""Round 21+22: autouse fixtures для сброса state между DSL-тестами.

Зеркало :mod:`tests.unit.services.ai.conftest` (Sprint 3 improvement #5)
расширенное с Round 22:

1. AIGateway composition root reset (``_overrides``, ``lru_cache``).
2. Svcs registry reset (``clear_registry()``) — закрывает
   test_react_isolated_uses_sandbox regression от test_agent_graph_tool_policy,
   который вызывает ``clear_registry()`` без proper teardown.

Без этих fixtures DSL тесты получают silent pollution от предыдущих
тестов → test ordering failures.

ADR-0393 (волна 18): добавлен autouse-fixture, разрешающий capability-гейт
для DSL-шагов БД. С 2026-10-29 процессоры БД объявляют
``required_capability`` (``db.read`` / ``db.write``) → прямой вызов
``process()`` без namespace'а роута получал бы fail-closed отказ
(ADR-0366). Тесты проверки поведения БД не должны дублировать проверку
capability — она покрыта отдельно (см. ``tests/unit/dsl/engine/capability/``).
"""

from __future__ import annotations

import pytest

from tests.unit._capability_mocks import patched_db_capability_allow


@pytest.fixture(autouse=True)
def _reset_ai_gateway_singleton_for_dsl() -> None:
    """Сбрасывает AIGateway composition root между DSL-тестами."""
    from src.backend.core.di.providers.ai import _build_ai_gateway_singleton, _overrides

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


@pytest.fixture(autouse=True)
def _allow_db_capability_for_dsl_processors(request: pytest.FixtureRequest) -> None:
    """ADR-0393: capability-гейт разрешён для тестов БД-процессоров.

    Тесты проверяют поведение БД (SQL, tenant-скоуп, лимиты), а не
    авторизацию — она покрыта в ``tests/unit/dsl/engine/capability/``.

    Модуль может отключить подмену, задав ``REAL_CAPABILITY_GATE = True``
    (тогда capability-гейт проверяется по-настоящему).
    """
    if getattr(request.module, "REAL_CAPABILITY_GATE", False):
        yield
        return
    with patched_db_capability_allow():
        yield
