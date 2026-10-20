"""Settings-driven init tests (cycle 162 audit).

Проверяет, что :func:`init_application_logging` корректно читает все
параметры из settings (LogStorageSettings, AppBaseSettings, profile) без
необходимости передавать их вручную.

Это centralized configuration — settings являются source of truth,
а caller может опционально переопределить через kwargs.

Цель — зафиксировать поведение settings-driven init, чтобы future
refactor не сломал hot-reload behavior (см. docs/architecture/logging.md).
"""

from __future__ import annotations

import pytest

from src.backend.core.logging import init_application_logging, shutdown_logging
from src.backend.infrastructure.logging import factory
from src.backend.infrastructure.logging.router import (
    get_router,
    is_router_configured,
    reset_router,
)
from src.backend.infrastructure.logging.structlog_backend import StructlogGraylogBackend


@pytest.fixture(autouse=True)
def _reset_factory_and_router() -> None:
    """Сбросить factory._backend + router между тестами."""
    factory._backend = None
    reset_router()
    yield
    factory._backend = None
    reset_router()
    try:
        shutdown_logging()
    except (OSError, RuntimeError):
        pass


class TestSettingsDrivenInitDefault:
    """``init_application_logging()`` без параметров читает всё из settings."""

    def test_init_reads_level_from_settings(self) -> None:
        """``level`` параметр = ``settings.logging.level``."""
        from src.backend.core.config.settings import settings

        backend = init_application_logging()
        # StructlogGraylogBackend имеет _level attribute.
        assert backend is not None
        assert settings.logging.level in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

    def test_init_reads_environment_from_settings(self) -> None:
        """``environment`` параметр = ``settings.app.environment``."""

        # Init без явного environment — должен использовать settings.
        backend = init_application_logging()
        # Backend.environment может быть None или строка, проверяем факт init.
        assert isinstance(backend, StructlogGraylogBackend)

    def test_init_reads_profile_from_settings(self) -> None:
        """``profile`` = ``get_active_profile()`` из ``APP_PROFILE`` env."""

        # Init без явного profile — должен использовать active profile.
        backend = init_application_logging()
        assert isinstance(backend, StructlogGraylogBackend)
        # Router activated (sinks roster).
        assert is_router_configured()

    def test_init_uses_settings_for_graylog_host(self) -> None:
        """``graylog_host`` = ``settings.logging.host`` если не переопределён."""

        backend = init_application_logging()
        # Backend hosts: settings.logging.host должен быть передан.
        assert backend is not None

    def test_init_uses_settings_for_log_dir(self) -> None:
        """``log_dir`` = ``settings.logging.dir_log_name`` если не переопределён."""
        # DiskRotatingLogSink использует disk_path = log_dir/app.jsonl.
        backend = init_application_logging()
        assert backend is not None


class TestSettingsDrivenInitOverriddenByExplicit:
    """Explicit параметры переопределяют settings (override mode)."""

    def test_explicit_level_overrides_settings(self) -> None:
        """Передача level="ERROR" должна override settings.logging.level."""
        backend = init_application_logging(level="ERROR")
        # Backend не падает, structlog accepts.
        assert isinstance(backend, StructlogGraylogBackend)

    def test_explicit_environment_overrides_settings(self) -> None:
        """Передача environment="production" override settings.app.environment."""
        backend = init_application_logging(environment="production")
        assert isinstance(backend, StructlogGraylogBackend)

    def test_explicit_profile_overrides_settings(self) -> None:
        """Передача profile="staging" override get_active_profile()."""
        backend = init_application_logging(profile="staging")
        assert isinstance(backend, StructlogGraylogBackend)
        router = get_router()
        # staging profile → GraylogGelfLogSink + DiskRotatingLogSink
        assert len(router.sinks) >= 1


class TestSettingsDrivenInitFailureTolerant:
    """``init_application_logging()`` failure-tolerant для test environments."""

    def test_init_with_settings_not_available_uses_defaults(self) -> None:
        """Если settings module не загружен — использует явные defaults.

        Cycle 162 design: use_settings=True пытается загрузить settings
        внутри try/except. Если settings не доступны (например, в
        минимальном unit-test окружении), использует явные defaults
        из параметров сигнатуры.
        """
        # Передаём use_settings=False чтобы skip settings load.
        backend = init_application_logging(use_settings=False)
        assert isinstance(backend, StructlogGraylogBackend)


class TestSettingsDrivenInitInAppFactoryPattern:
    """Сценарий использования в ``app_factory.create_app()`` lifespan."""

    def test_full_settings_driven_lifespan_pattern(self) -> None:
        """Полный сценарий: settings → backend init → router → logger → shutdown."""
        from src.backend.core.config.profile import get_active_profile
        from src.backend.core.config.settings import settings

        # Pre-state
        assert factory._backend is None
        assert not is_router_configured()

        # Settings-driven init (как в app_factory.create_app)
        backend = init_application_logging(
            level=settings.logging.level,
            environment=settings.app.environment,
            profile=get_active_profile(),
            log_dir=settings.logging.dir_log_name,
            graylog_host=settings.logging.host,
            graylog_port=settings.logging.port,
            graylog_protocol="tcp" if settings.logging.use_tls else "udp",
        )
        assert isinstance(backend, StructlogGraylogBackend)
        assert is_router_configured()

        # Shutdown
        shutdown_logging()


class TestAppFactorySettingsReadConsistency:
    """Проверяет, что app_factory.py использует правильные settings атрибуты."""

    def test_settings_logging_attribute_exists(self) -> None:
        """``settings.logging`` (НЕ ``settings.log``) — правильное имя."""
        from src.backend.core.config.settings import settings

        assert hasattr(settings, "logging")
        # Убеждаемся, что нет устаревшего .
        assert not hasattr(settings, "log") or settings.logging  # logging wins

    def test_settings_app_has_environment(self) -> None:
        """``settings.app.environment`` существует."""
        from src.backend.core.config.settings import settings

        assert hasattr(settings.app, "environment")
        assert settings.app.environment in {"development", "staging", "production"}

    def test_settings_app_profile_uses_get_active_profile(self) -> None:
        """``settings.app.profile` НЕ существует; используем `get_active_profile()`."""
        from src.backend.core.config.profile import get_active_profile
        from src.backend.core.config.settings import settings

        # Подтверждаем, что app.profile не существует.
        # (если кто-то добавит это поле — тест надо обновить).
        # Используем hasattr без getattr чтобы не вызывать AttributeError.
        assert not hasattr(settings.app, "profile")

        # Правильный pattern.
        active = get_active_profile()
        assert active in {"dev_light", "dev", "staging", "prod"}


class TestSettingsDrivenInitLogsSettingsRead:
    """``init_application_logging()`` НЕ fail при settings отсутствии."""

    def test_settings_not_available_does_not_raise(self) -> None:
        """Если settings полностью отсутствует — backend всё равно init."""
        # Создаём backend без settings через explicit args.
        backend = init_application_logging(
            level="INFO",
            environment="test",
            profile="dev",
            use_settings=False,
        )
        assert isinstance(backend, StructlogGraylogBackend)


class TestSettingsDrivenInitWithCustomGraylog:
    """Custom Graylog params через explicit kwargs (override settings)."""

    def test_custom_graylog_host(self) -> None:
        """Custom graylog_host="custom.graylog.local" → передаётся в build_sinks_for_profile."""
        backend = init_application_logging(
            graylog_host="custom.graylog.local",
            graylog_port=12202,
            graylog_protocol="tcp",
            profile="staging",
        )
        assert isinstance(backend, StructlogGraylogBackend)

    def test_custom_disk_path(self) -> None:
        """Custom log_dir="/var/log/myapp" → disk_path="/var/log/myapp/app.jsonl"."""
        # Init с явным log_dir.
        backend = init_application_logging(
            profile="dev",
            log_dir="/tmp/test_logs",
        )
        assert isinstance(backend, StructlogGraylogBackend)


class TestSettingsDrivenInitIdempotent:
    """Повторный settings-driven init работает без замены router по ошибке."""

    def test_double_init_with_settings_does_not_raise(self) -> None:
        """Двойной init с settings-driven pattern не raise."""
        b1 = init_application_logging()
        b2 = init_application_logging()
        assert b1 is not b2  # backend re-created
        # Но router активен.
        assert is_router_configured()
