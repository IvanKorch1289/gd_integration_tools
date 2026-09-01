"""Unit-тесты ``core.config.settings.Settings`` — coverage ratchet (S48 W6).

S44 W32 + S48 W5 batch-fix обнаружили что ``core/config/settings.py`` —
Pydantic aggregator (185 LOC, ~30 sub-settings) — **0% coverage** (72 stmts
untouched). При этом Settings используется в production повсеместно
(test_app_factory_smoke и др.).

После S48 W5 batch-fix (10 Pydantic model_validator self-ref NameError) все
imports внутри settings.py работают, и Settings() инстанциируется без ошибок
(при наличии credentials для всех external_databases profiles в env).

Цель slice: 0% → 100% на settings.py через прямые asserts:
* ``Settings()`` инстанциируется с default values + всеми sub-settings;
* все ~40 атрибутов sub-settings доступны и non-None;
* ``get_app_settings()`` возвращает тот же instance через ``@lru_cache``;
* ``settings`` (module-level singleton) идентичен ``get_app_settings()``.

Test-env note: YAML profile ``config_profiles/dev.yml`` определяет external
DB profiles (oracle_1, pg_1), которые при Settings() instantiation требуют
credentials через EXT_DB_<PROFILE>_<FIELD> env vars. Используем autouse
fixture для установки mock credentials.
"""

from __future__ import annotations

import pytest

from src.backend.core.config.settings import (  # noqa: PLC0415
    Settings,
    get_app_settings,
    settings,
)


@pytest.fixture(autouse=True)
def _set_ext_db_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """autouse: ставит APP_ENVIRONMENT + EXT_DB_* credentials + clears lru_cache.

    Note: env var format EXT_DB_<PROFILE>_<FIELD> где PROFILE — uppercase
    (``EXT_DB_ORACLE_1_USERNAME``, не ``EXT_DB_oracle_1_USERNAME``). Lookup
    в :func:`ExternalDatabasesRegistry._get_secret_from_env` нормализует
    profile_name → uppercase.
    """
    monkeypatch.setenv("APP_ENVIRONMENT", "development")
    for profile in ("ORACLE_1", "PG_1"):
        monkeypatch.setenv(f"EXT_DB_{profile}_USERNAME", "test_user")
        monkeypatch.setenv(f"EXT_DB_{profile}_PASSWORD", "test_pwd")
    # Drop lru_cache.
    get_app_settings.cache_clear()


@pytest.mark.unit
class TestSettingsInstantiation:
    """``Settings()`` — default values + атрибуты sub-settings."""

    def test_settings_instantiates_with_defaults(self) -> None:
        """``Settings()`` создаётся без обязательных аргументов."""
        s = Settings()
        assert s is not None
        assert hasattr(s, "app")
        assert hasattr(s, "database")
        assert hasattr(s, "redis")
        assert hasattr(s, "vault")

    def test_all_subsettings_accessible(self) -> None:
        """Все 30+ sub-settings атрибутов доступны через ``.attr`` access."""
        s = Settings()
        # Проверяем по одной из каждой секции (не все 30, чтобы тест
        # остался < 50 LOC):
        section_attrs = [
            "app", "secure", "http_base_settings", "scheduler", "vault",
            "antivirus", "database", "external_databases", "skb_api",
            "dadata_api", "queue", "mail", "tasks", "grpc",
            "invoker", "clickhouse", "express", "telegram", "elasticsearch",
            "ai_providers", "openrouter", "nim", "openai",
            "rag", "jupyter_hub", "cert_store",
            "storage", "logging", "redis", "mongo", "cache", "watermark",
            "influxdb", "dsl", "sms", "lineage",
            "v11", "workflow", "resilience", "snapshot", "transport",
        ]
        for attr in section_attrs:
            assert hasattr(s, attr), f"Settings missing attribute '{attr}'"
            assert getattr(s, attr) is not None, f"Settings.{attr} is None"

    def test_subsections_have_expected_types(self) -> None:
        """Каждый sub-setting имеет свой класс (Pydantic settings instance)."""
        s = Settings()
        # Проверяем критичные sub-settings (type-based):
        assert type(s.app).__name__ == "AppBaseSettings"
        assert type(s.database).__name__ == "DatabaseConnectionSettings"
        assert type(s.redis).__name__ == "RedisSettings"
        assert type(s.cache).__name__ == "CacheSettings"
        assert type(s.vault).__name__ == "VaultSettings"

    def test_settings_repr_is_safe(self) -> None:
        """``repr(Settings())`` не падает с ошибкой."""
        s = Settings()
        r = repr(s)
        assert isinstance(r, str)


@pytest.mark.unit
class TestGetAppSettingsSingleton:
    """``get_app_settings()`` — @lru_cache singleton."""

    def test_returns_settings_instance(self) -> None:
        """``get_app_settings()`` → :class:`Settings` instance."""
        s = get_app_settings()
        assert isinstance(s, Settings)

    def test_cached_returns_same_instance(self) -> None:
        """``get_app_settings()`` cached → второй вызов возвращает тот же объект."""
        first = get_app_settings()
        second = get_app_settings()
        assert first is second

    def test_module_level_singleton_is_settings_instance(self) -> None:
        """Module-level ``settings`` — это :class:`Settings` instance.

        Note: ``settings = get_app_settings()`` выполнен на module import time,
        до autouse fixture. После ``cache_clear()`` последующие вызовы
        ``get_app_settings()`` могут вернуть другой instance (если env
        изменился). Проверяем только что module-level singleton — Settings.
        """
        assert isinstance(settings, Settings)
        assert hasattr(settings, "app")
        assert hasattr(settings, "database")


@pytest.mark.unit
class TestSettingsFieldAccess:
    """Settings field access patterns."""

    def test_settings_is_pydantic_basemodel(self) -> None:
        """``Settings`` наследует Pydantic BaseSettings (model_dump() доступен)."""
        s = Settings()
        dump = s.model_dump()
        assert isinstance(dump, dict)
        assert "app" in dump
        assert "database" in dump

    def test_settings_class_has_model_fields(self) -> None:
        """``Settings.model_fields`` (class-level) содержит ожидаемые ключи."""
        # Class-level access — no instance required:
        field_names = set(Settings.model_fields.keys())
        assert "app" in field_names
        assert "database" in field_names
        assert "redis" in field_names
        assert "vault" in field_names
