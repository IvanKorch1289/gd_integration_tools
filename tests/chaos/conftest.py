"""Pytest-конфигурация chaos-suite.

Подключает фикстуры из ``testkit/chaos_fixtures.py`` и применяет общие
маркеры. Также пропускает все тесты в окружении, где переменная
``ENABLE_CHAOS_TESTS`` явно установлена в ``0`` (например, локальный
быстрый pytest run).
"""

from __future__ import annotations

import os

import pytest

# Импорт фикстур: pytest автоматически их зарегистрирует благодаря
# conftest-механизму.
from testkit.chaos_fixtures import (  # noqa: F401
    apply_disconnect,
    apply_latency,
    apply_random_drop,
    toxiproxy_clickhouse,
    toxiproxy_es,
    toxiproxy_graylog,
    toxiproxy_kafka,
    toxiproxy_nats,
    toxiproxy_pg,
    toxiproxy_rabbitmq,
    toxiproxy_redis,
    toxiproxy_s3,
    toxiproxy_temporal,
    toxiproxy_vault,
)


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Авто-помечает все тесты в этом каталоге маркерами chaos и requires_toxiproxy.

    Args:
        config: pytest config (не используется).
        items: список собранных тестовых items.
    """
    skip_chaos = pytest.mark.skip(reason="ENABLE_CHAOS_TESTS=0")
    disabled = os.environ.get("ENABLE_CHAOS_TESTS", "1") == "0"

    for item in items:
        item.add_marker(pytest.mark.chaos)
        item.add_marker(pytest.mark.requires_toxiproxy)
        if disabled:
            item.add_marker(skip_chaos)
