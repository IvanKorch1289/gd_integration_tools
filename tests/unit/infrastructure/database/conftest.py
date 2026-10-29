"""Autouse-фикстуры для тестов инфраструктурной БД.

ADR-0393 (волна 18): DSL-процессоры доступа к БД объявляют
``required_capability`` (``db.read`` / ``db.write``) → прямой вызов
``process()`` без namespace'а роута получал бы fail-closed отказ
(ADR-0366). Тесты проверки поведения БД не дублируют проверку
авторизации — она покрыта отдельно (см.
``tests/unit/dsl/engine/capability/``).

Модуль может отключить подмену, задав ``REAL_CAPABILITY_GATE = True``.
"""

from __future__ import annotations

import pytest

from tests.unit._capability_mocks import patched_db_capability_allow


@pytest.fixture(autouse=True)
def _allow_db_capability_for_db_runtime(request: pytest.FixtureRequest) -> None:
    """ADR-0393: capability-гейт разрешён для тестов runtime'а БД."""
    if getattr(request.module, "REAL_CAPABILITY_GATE", False):
        yield
        return
    with patched_db_capability_allow():
        yield
