"""
Корневой conftest для всей тестовой инфраструктуры.

Предоставляет:
  - svcs_container: изолированный DI-контейнер на каждый тест
  - test_db: SQLAlchemy async engine против тестовой БД
  - test_cache: Redis клиент против тестового Redis

Зависимости: pytest-asyncio, svcs.
"""

from __future__ import annotations

import pytest
import svcs


@pytest.fixture
def svcs_container() -> svcs.Container:
    """Изолированный svcs.Container для одного теста.

    Создаётся поверх глобального Registry; все регистрации видны,
    но стейт сбрасывается после теста.
    """
    from src.backend.core.svcs_registry import registry

    container = svcs.Container(registry)
    yield container
    container.close()


@pytest.fixture
def test_db():
    """Заглушка фикстуры тестовой БД.

    Для реального подключения используйте testcontainers в
    tests/integration/conftest.py.
    """
    return None


@pytest.fixture
def test_cache():
    """Заглушка фикстуры тестового кэша.

    Для реального подключения используйте testcontainers в
    tests/integration/conftest.py.
    """
    return None
