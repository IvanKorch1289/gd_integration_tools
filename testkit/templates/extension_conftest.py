"""Шаблон ``conftest.py`` для тестов ``extensions/<name>/tests/``.

Скопируйте этот файл в ``extensions/<your_name>/tests/conftest.py`` и
адаптируйте имя плагина в фикстуре ``plugin_under_test``. Pre-wired
триада фикстур (plugin loader + DB snapshot + S3 mock) покрывает
типичные сценарии unit-тестов extension:

* загрузка ``plugin.toml`` через :func:`loaded_plugin`;
* сидирование локальной SQLite-копии через :func:`db_snapshot`;
* in-memory S3 через :func:`s3_client` (moto).

Heavy-deps (moto, testcontainers, plugin runtime) lazy-импортируются
внутри fixture; при отсутствии extras = ``testkit`` тест помечается
``pytest.skip``.

См. также:
    * ``testkit/fixtures/db.py`` — Postgres testcontainer;
    * ``testkit/fixtures/redis.py`` — Redis testcontainer;
    * ``testkit/fixtures/temporal.py`` — Temporal testcontainer;
    * ``testkit/fixtures/tenant.py`` — TenantContext per-test override.
"""

from __future__ import annotations

import pytest

# Pre-wired фикстуры — pytest подхватит их автоматически благодаря
# импорту в conftest.py. Если фикстура не нужна — закомментируйте.
from testkit.fixtures.db_snapshot import db_snapshot  # noqa: F401
from testkit.fixtures.plugin_loader import (  # noqa: F401
    loaded_plugin,
    plugin_runtime,
)
from testkit.fixtures.s3_mock import s3_client, s3_mock  # noqa: F401


# === Адаптируйте под свой extension ===

PLUGIN_NAME = "your_extension_name"  # ← поменяйте на имя из plugin.toml


@pytest.fixture(scope="session")
def plugin_under_test(loaded_plugin):
    """Загруженный spec вашего плагина (alias для удобства)."""
    return loaded_plugin(PLUGIN_NAME)


# === Хелперы для маркеров (опционально) ===


def pytest_configure(config):
    """Регистрирует custom markers для extension-тестов."""
    config.addinivalue_line(
        "markers", "capability(name): отметка теста на использование capability"
    )
    config.addinivalue_line(
        "markers", "tenant(name): запустить тест в контексте указанного tenant"
    )
