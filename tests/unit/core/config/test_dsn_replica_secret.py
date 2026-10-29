"""ADR-0381 — ``replica_dsn`` как секрет (ADR-0378) + дефолт ретраев.

Дефекты волны 16 (кластер X2):

1. ``replica_dsn`` объявлен как ``str`` и содержит пароль в открытом виде:
   ``model_dump()``/``model_dump_json()`` отдавали его целиком, а
   ``repr`` модели — тоже. По образцу ADR-0378 — ``SecretStr`` + маскирование
   в дампах (рабочее значение остаётся доступным через
   ``get_secret_value()``).
2. ``max_retries`` в ``config_profiles/base.yml`` = 0 и ни один профиль его
   не переопределял → повтор при установлении соединения был выключен
   (настройка мёртвая).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import SecretStr

from src.backend.core.config.database import DatabaseConnectionSettings

_REPO_ROOT = Path(__file__).resolve().parents[4]

_REPLICA_DSN = "postgresql+asyncpg://replica_user:s3cr3t@pg-replica:5432/main_db"


def _make_settings(**overrides: Any) -> DatabaseConnectionSettings:
    """Создаёт ``DatabaseConnectionSettings`` с валидными дефолтами."""
    defaults: dict[str, Any] = {
        "type": "postgresql",
        "username": "user",
        "password": "pwd",
        "host": "localhost",
        "port": 5432,
        "name": "mydb",
        "async_driver": "asyncpg",
        "sync_driver": "psycopg",
        "ssl_mode": None,
        "ca_bundle": None,
    }
    defaults.update(overrides)
    return DatabaseConnectionSettings(**defaults)


@pytest.mark.unit
class TestReplicaDsnIsSecret:
    """``replica_dsn`` — секрет: типизирован и замаскирован в дампах."""

    def test_replica_dsn_is_secret_str(self) -> None:
        """Поле типизировано ``SecretStr``."""
        settings = _make_settings(replica_dsn=_REPLICA_DSN)

        assert isinstance(settings.replica_dsn, SecretStr)
        assert settings.replica_dsn.get_secret_value() == _REPLICA_DSN

    def test_replica_dsn_masked_in_model_dump(self) -> None:
        """``model_dump()`` не содержит пароля реплики."""
        settings = _make_settings(replica_dsn=_REPLICA_DSN)

        dumped = settings.model_dump()
        assert "s3cr3t" not in str(dumped)
        assert "***" in str(dumped["replica_dsn"])

    def test_replica_dsn_masked_in_model_dump_json(self) -> None:
        """``model_dump_json()`` не содержит пароля реплики."""
        settings = _make_settings(replica_dsn=_REPLICA_DSN)

        dumped_json = settings.model_dump_json()
        assert "s3cr3t" not in dumped_json
        assert "***" in dumped_json

    def test_replica_dsn_absent_by_default(self) -> None:
        """Без реплики поле остаётся ``None``."""
        settings = _make_settings()
        assert settings.replica_dsn is None


@pytest.mark.unit
class TestReplicaEngineUsesPlainDsn:
    """Движок реплики получает настоящий DSN (маскирование — только в дампах)."""

    def test_replica_engine_created_with_plain_password(self) -> None:
        """``replica_engine`` создан и URL внутри — с настоящим паролем."""
        from src.backend.infrastructure.database.database.initializer import (
            DatabaseInitializer,
        )

        settings = _make_settings(replica_dsn=_REPLICA_DSN)
        initializer = DatabaseInitializer(settings=settings, name="probe")

        assert initializer.replica_engine is not None
        assert initializer.replica_session_maker is not None
        rendered = initializer.replica_engine.url.render_as_string(hide_password=False)
        assert "s3cr3t" in rendered

    def test_no_replica_no_engine(self) -> None:
        """Без ``replica_dsn`` replica-движок не создаётся."""
        from src.backend.infrastructure.database.database.initializer import (
            DatabaseInitializer,
        )

        initializer = DatabaseInitializer(settings=_make_settings(), name="probe")
        assert initializer.replica_engine is None
        assert initializer.replica_session_maker is None


@pytest.mark.unit
class TestConnectionRetriesEnabled:
    """``database.max_retries`` не должен быть мёртвой настройкой."""

    def test_base_profile_enables_retries(self) -> None:
        """``config_profiles/base.yml`` — ``max_retries`` > 0.

        ``max_retries`` читается ``infrastructure/database/session_manager.py``
        (повтор при установлении соединения); при значении 0 повторов не
        было ни одного — настройка была мёртвой.
        """
        base = yaml.safe_load(
            (_REPO_ROOT / "config_profiles" / "base.yml").read_text(encoding="utf-8")
        )
        assert base["database"]["max_retries"] > 0
