"""Unit-тесты: внешний контур БД поддерживает только postgresql/oracle.

Wave 13 Q10: внешний контур объявлял 7 типов СУБД (общий enum
``DatabaseTypeChoices``), но реализовывал 2 — ошибка возникала только в
момент подключения (``_build_dsn`` → ``NotImplementedError``), а не при
валидации конфигурации.

Контракт: неподдерживаемый тип внешнего контура отвергается на этапе
валидации конфигурации (fail-fast), с понятным сообщением.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from src.backend.core.config.external_databases import (
    ExternalDatabaseItemSettings,
    ExternalDatabasesSettings,
)

# Типы, которые реализует внешний контур (dispatch + DSN).
SUPPORTED_EXTERNAL_TYPES: tuple[str, ...] = ("postgresql", "oracle")

# Типы из общего enum, которые доступны ТОЛЬКО во внутренней БД
# (core/config/database.py) и не реализованы во внешнем контуре.
UNSUPPORTED_EXTERNAL_TYPES: tuple[str, ...] = (
    "mssql",
    "mysql",
    "db2",
    "clickhouse",
    "sqlite",
)


def _item_payload(db_type: str, **overrides: Any) -> dict[str, Any]:
    """Собирает минимальный валидный payload внешнего подключения."""
    payload: dict[str, Any] = {
        "name": "ext_1",
        "profile_name": "ext_1",
        "type": db_type,
        "host": "10.10.10.11",
        "port": 1521,
        "async_driver": "asyncpg",
        "sync_driver": "psycopg2",
        "schema": "public",
    }
    payload.update(overrides)
    return payload


@pytest.mark.unit
class TestExternalDatabaseTypeSupport:
    """Fail-fast на этапе конфигурации для неподдерживаемых типов СУБД."""

    @pytest.mark.parametrize("db_type", UNSUPPORTED_EXTERNAL_TYPES)
    def test_unsupported_type_rejected_on_item_validation(self, db_type: str) -> None:
        """Неподдерживаемый тип отвергается валидатором item-конфига."""
        with pytest.raises(ValidationError) as exc_info:
            ExternalDatabaseItemSettings(**_item_payload(db_type))

        message = str(exc_info.value)
        assert db_type in message, f"Тип '{db_type}' не упомянут в ошибке: {message}"
        for supported in SUPPORTED_EXTERNAL_TYPES:
            assert supported in message, (
                f"Поддерживаемый тип '{supported}' не упомянут в ошибке: {message}"
            )

    @pytest.mark.parametrize("db_type", UNSUPPORTED_EXTERNAL_TYPES)
    def test_unsupported_type_rejected_on_registry_validation(
        self, db_type: str
    ) -> None:
        """Реестр внешних БД отвергает профиль с неподдерживаемым типом."""
        with pytest.raises(ValidationError) as exc_info:
            ExternalDatabasesSettings(
                echo=False,
                pool_size=5,
                max_overflow=5,
                pool_recycle=1800,
                pool_timeout=30,
                connect_timeout=10,
                command_timeout=30,
                max_retries=0,
                circuit_breaker_max_failures=5,
                circuit_breaker_reset_timeout=30,
                slow_query_threshold=1.0,
                connections=[_item_payload(db_type)],
            )

        message = str(exc_info.value)
        assert db_type in message, f"Тип '{db_type}' не упомянут в ошибке: {message}"

    def test_supported_types_accepted(self) -> None:
        """postgresql и oracle по-прежнему принимаются конфигом."""
        postgres = ExternalDatabaseItemSettings(
            **_item_payload("postgresql", port=5432, db_name="analytics")
        )
        oracle = ExternalDatabaseItemSettings(
            **_item_payload("oracle", sid="ORCL", db_name=None)
        )

        assert postgres.type == "postgresql"
        assert oracle.type == "oracle"

    def test_error_message_mentions_internal_database(self) -> None:
        """Сообщение подсказывает, где тип доступен на самом деле."""
        with pytest.raises(ValidationError) as exc_info:
            ExternalDatabaseItemSettings(**_item_payload("mssql"))

        message = str(exc_info.value)
        assert "core/config/database.py" in message, (
            f"Ошибка не указывает на внутреннюю БД: {message}"
        )
