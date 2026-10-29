"""A7/A8/A10 (ADR-0385): безопасность внешнего контура БД.

A7 — пароль в ``model_dump()``: computed-поля ``async_connection_url`` /
``sync_connection_url`` содержали DSN с паролем открытым текстом, и
``GET /api/v1/admin/config`` отдавал пароль.

A8 — ``settings.model_dump()`` ронял admin-эндпоинт (500):
``ValueError: Не найден username для внешней БД 'oracle_1'`` и
``DatabaseDriverError: 'psycopg' не установлен``. Computed-поля не должны
ронять дамп: отсутствие кредов/драйвера — деградация, а не исключение.

A10 — ``external_databases.connections[]``: item-модель принимала
``extra=ignore``, поэтому опечатки (``sslmode``, ``pool_sze``) молча
терялись. Теперь лишние поля — ошибка валидации.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from src.backend.core.config.external_databases import (
    ExternalDatabaseConnectionSettings,
    ExternalDatabaseItemSettings,
    ExternalDatabasesSettings,
)

SECRET = "ExtS3cret!"


def _item_payload(db_type: str = "postgresql", **overrides: Any) -> dict[str, Any]:
    """Минимальный валидный payload внешнего подключения."""
    payload: dict[str, Any] = {
        "name": "ext_1",
        "profile_name": "ext_1",
        "type": db_type,
        "host": "10.10.10.11",
        "port": 5432,
        "async_driver": "asyncpg",
        "sync_driver": "psycopg",
        "schema": "public",
    }
    if db_type == "postgresql":
        payload["db_name"] = "analytics"
    else:
        payload["sid"] = "ORCL"
    payload.update(overrides)
    return payload


def _connection_payload(**overrides: Any) -> dict[str, Any]:
    """Payload итогового подключения (с кред-ами)."""
    payload: dict[str, Any] = {
        **_item_payload(),
        "echo": False,
        "username": "extu",
        "password": SECRET,
        "pool_size": 5,
        "max_overflow": 5,
        "pool_recycle": 1800,
        "pool_timeout": 30,
        "connect_timeout": 10,
        "command_timeout": 30,
        "max_retries": 0,
        "circuit_breaker_max_failures": 5,
        "circuit_breaker_reset_timeout": 30,
        "slow_query_threshold": 1.0,
    }
    payload.update(overrides)
    return payload


@pytest.mark.unit
class TestConnectionUrlMasking:
    """A7: пароль не должен попадать в дамп модели."""

    def test_model_dump_masks_password(self) -> None:
        """``model_dump()`` маскирует пароль в DSN."""
        connection = ExternalDatabaseConnectionSettings(**_connection_payload())
        dumped = connection.model_dump()
        assert "ExtS3cret" not in dumped["async_connection_url"]
        assert "ExtS3cret" not in dumped["sync_connection_url"]
        assert "***" in dumped["async_connection_url"]

    def test_model_dump_json_masks_password(self) -> None:
        """``model_dump_json()`` маскирует пароль в DSN."""
        connection = ExternalDatabaseConnectionSettings(**_connection_payload())
        dumped = connection.model_dump_json()
        assert "ExtS3cret" not in dumped
        assert "***" in dumped

    def test_attribute_keeps_working_dsn(self) -> None:
        """Атрибут DSN остаётся рабочим (SQLAlchemy подключается с паролем)."""
        connection = ExternalDatabaseConnectionSettings(**_connection_payload())
        assert "ExtS3cret%21" in connection.async_connection_url
        assert "extu" in connection.async_connection_url


@pytest.mark.unit
class TestDumpDoesNotRaise:
    """A8: computed-поля не роняют дамп."""

    def test_registry_dump_without_credentials(self) -> None:
        """Реестр без кредов дампится без исключения."""
        registry = ExternalDatabasesSettings(
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
            connections=[_item_payload()],
        )
        dumped = registry.model_dump()
        assert "profiles" in dumped

    def test_connection_dump_without_username(self) -> None:
        """Подключение без кредов дампится (username опционален)."""
        connection = ExternalDatabaseConnectionSettings(
            **_connection_payload(username=None, password=None)
        )
        dumped = connection.model_dump()
        assert dumped["async_connection_url"]

    def test_missing_driver_does_not_break_dump(self) -> None:
        """Неустановленный драйвер не роняет дамп."""
        connection = ExternalDatabaseConnectionSettings(
            **_connection_payload(sync_driver="definitely_not_installed_driver")
        )
        dumped = connection.model_dump()
        assert "definitely_not_installed_driver" in dumped["sync_connection_url"]

    def test_settings_model_dump_does_not_raise(self) -> None:
        """``Settings.model_dump()`` (admin-эндпоинт) не падает."""
        from src.backend.core.config.settings import settings

        dumped = settings.model_dump()
        assert "external_databases" in dumped


@pytest.mark.unit
class TestConnectionsRejectUnknownFields:
    """A10: опечатки в ``connections[]`` — ошибка, а не тихая потеря."""

    @pytest.mark.parametrize("typo", ["sslmode", "pool_sze", "unknown_key"])
    def test_unknown_field_rejected(self, typo: str) -> None:
        """Лишний ключ в item-модели отвергается валидатором."""
        payload = _item_payload()
        payload[typo] = "typo-value"
        with pytest.raises(ValidationError) as exc_info:
            ExternalDatabaseItemSettings(**payload)
        assert typo in str(exc_info.value)

    def test_known_fields_still_accepted(self) -> None:
        """Известные поля продолжают приниматься."""
        item = ExternalDatabaseItemSettings(**_item_payload(pool_size=10))
        assert item.pool_size == 10
