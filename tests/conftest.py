"""
Корневой conftest для всей тестовой инфраструктуры.

Предоставляет:
  - svcs_container: изолированный DI-контейнер на каждый тест
  - test_db: SQLAlchemy async engine против тестовой БД
  - test_cache: Redis клиент против тестового Redis
  - _set_test_env_vars: pytest_configure hook (S159 W3) sets DB
    env vars BEFORE module-level settings instantiation (env =
    pyproject.toml directive is a pytest-env plugin feature, not core).

Зависимости: pytest-asyncio, svcs.
"""

from __future__ import annotations

import os

import pytest
import svcs


def pytest_configure(config: pytest.Config) -> None:
    """S159 W3: set DB env vars before any test module is imported.

    pydantic_settings auto-loads from config_profiles/{profile}.yml.
    YAML has type=postgresql and no username — fails at module-level
    DatabaseConnectionSettings() instantiation. We override via env
    vars (env vars > YAML in pydantic_settings priority).
    """
    test_env = {
        "DB_USERNAME": "test_user",
        "DB_PASSWORD": "***",
        "DB_HOST": "localhost",
        "DB_PORT": "5432",
        "DB_NAME": "test_db",
        "MONGO_URI": "mongodb://localhost:27017/test",
        "MONGO_USERNAME": "test_user",
        "MONGO_PASSWORD": "***",
        "MONGO_HOST": "localhost",
        "MONGO_PORT": "27017",
        "MONGO_NAME": "test_db",
        "VAULT_ENABLED": "false",
        "LITELLM_ENABLED": "false",
    }
    for key, value in test_env.items():
        os.environ.setdefault(key, value)


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
