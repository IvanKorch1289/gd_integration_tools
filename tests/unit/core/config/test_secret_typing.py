"""TDD: ADR-0373 — типизация секретов как ``SecretStr`` (зона ``core/config``).

Поля, которые читаются ТОЛЬКО внутри ``src/backend/core/config/``, типизируются
как ``SecretStr``: значение маскируется в ``repr``/логах, а читатели
используют ``.get_secret_value()``.

Поля с читателями за пределами ``core/config`` (см. ADR-0373, «Последствия»)
намеренно оставлены ``str`` — это owner-задача отдельного кластера.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from src.backend.core.config.database import DatabaseConnectionSettings
from src.backend.core.config.mongo import MongoConnectionSettings

_DB_VALUES: dict[str, object] = {
    "type": "postgresql",
    "host": "db.example.com",
    "port": 5432,
    "name": "app",
    "username": "app_user",
    "password": "s3cr3t-db-pass",
    "pool_size": 10,
    "max_overflow": 10,
    "pool_recycle": 1800,
    "pool_timeout": 30,
    "connect_timeout": 10,
    "command_timeout": 30,
    "max_retries": 0,
    "circuit_breaker_max_failures": 10,
    "circuit_breaker_reset_timeout": 30,
    "slow_query_threshold": 1.0,
}

_MONGO_VALUES: dict[str, object] = {
    "username": "mongo_admin",
    "password": "s3cr3t-mongo-pass",
    "name": "app",
    "host": "mongo.example.com",
    "port": 27017,
    "min_pool_size": 10,
    "max_pool_size": 50,
    "timeout": 5000,
}


class TestDatabaseSecretTyping:
    """``DatabaseConnectionSettings.password`` — ``SecretStr``."""

    def test_password_field_is_secret_str(self) -> None:
        """Поле пароля типизировано как ``SecretStr | None`` (default None)."""
        field = DatabaseConnectionSettings.model_fields["password"]
        assert "SecretStr" in str(field.annotation)
        assert field.default is None

    def test_password_is_masked_in_repr(self) -> None:
        """Значение пароля не попадает в repr модели."""
        settings = DatabaseConnectionSettings.model_validate(_DB_VALUES)
        assert "s3cr3t-db-pass" not in repr(settings)

    def test_dsn_contains_plain_password(self) -> None:
        """DSN собирается из реального значения (``get_secret_value``)."""
        settings = DatabaseConnectionSettings.model_validate(_DB_VALUES)
        assert "s3cr3t-db-pass" in settings.async_connection_url

    def test_empty_password_is_rejected(self) -> None:
        """Пустой пароль по-прежнему отвергается валидатором (fail-closed)."""
        with pytest.raises(ValidationError):
            DatabaseConnectionSettings.model_validate({**_DB_VALUES, "password": ""})


class TestMongoSecretTyping:
    """``MongoConnectionSettings.password`` — ``SecretStr``."""

    def test_password_field_is_secret_str(self) -> None:
        """Поле пароля типизировано как SecretStr (обязательное, без default)."""
        field = MongoConnectionSettings.model_fields["password"]
        assert field.annotation is SecretStr
        assert field.is_required()

    def test_password_is_masked_in_repr(self) -> None:
        """Значение пароля не попадает в repr модели."""
        settings = MongoConnectionSettings.model_validate(_MONGO_VALUES)
        assert "s3cr3t-mongo-pass" not in repr(settings)

    def test_connection_string_contains_plain_password(self) -> None:
        """Connection string собирается из реального значения."""
        settings = MongoConnectionSettings.model_validate(_MONGO_VALUES)
        assert "s3cr3t-mongo-pass" in settings.connection_string
