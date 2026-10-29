"""Дефолты logging-стека из настроек, а не из sentinel-значений.

ADR-0392 (волна 18, кластер G3 — логирование).

Дефекты:

* (4) ``infrastructure/logging/factory.py``: sentinel ``if level == "INFO"``
  — ЯВНО переданный ``level="INFO"`` подменялся на ``settings.logging.level``
  (в тестовом окружении это ``DEBUG``), т.е. явный аргумент игнорировался;
* (5) ``infrastructure/logging/structlog_backend.py``: ``environment="production"``
  в lazy-пути (``get_logger()`` без ``init_application_logging``) — CLI и
  воркеры всегда писали ``environment=production`` независимо от профиля.
"""

from __future__ import annotations

import logging

import pytest

from src.backend.core.logging import init_application_logging
from src.backend.infrastructure.logging import factory


@pytest.fixture(autouse=True)
def _reset_factory() -> None:
    """Сбросить глобальный backend factory между тестами."""
    factory._backend = None
    yield
    factory._backend = None
    try:
        factory.shutdown_logging()
    except OSError, RuntimeError:
        pass


@pytest.mark.unit
class TestExplicitLevelIsRespected:
    """Явный ``level=`` не должен подменяться значением из settings."""

    def test_explicit_info_level_is_not_overridden(self) -> None:
        """``level="INFO"`` → root-logger остаётся на INFO.

        До фикса sentinel ``if level == "INFO"`` подменял аргумент на
        ``settings.logging.level`` (в тестовом окружении — ``DEBUG``).
        """
        init_application_logging(level="INFO")

        assert logging.getLogger().level == logging.INFO

    def test_explicit_debug_level_is_respected(self) -> None:
        """``level="DEBUG"`` → root-logger на DEBUG."""
        init_application_logging(level="DEBUG")

        assert logging.getLogger().level == logging.DEBUG

    def test_explicit_error_level_is_respected(self) -> None:
        """``level="ERROR"`` → root-logger на ERROR."""
        init_application_logging(level="ERROR")

        assert logging.getLogger().level == logging.ERROR


@pytest.mark.unit
class TestLevelDefaultFromSettings:
    """Без явного ``level=`` — берётся значение из settings."""

    def test_default_level_matches_settings(self) -> None:
        """``init_application_logging()`` → level = ``settings.logging.level``."""
        from src.backend.core.config.settings import settings

        init_application_logging()

        assert logging.getLogger().level == getattr(
            logging, settings.logging.level.upper()
        )


@pytest.mark.unit
class TestEnvironmentDefaultFromSettings:
    """Lazy-путь ``get_logger()`` — окружение из ``settings.app.environment``."""

    def test_lazy_logger_uses_settings_environment(self) -> None:
        """Без ``init_application_logging`` окружение = профиль, не production."""
        import structlog

        from src.backend.core.config.settings import settings

        factory.get_logger("test.lazy.environment")

        context = structlog.contextvars.get_contextvars()
        assert context.get("environment") == settings.app.environment
        assert context.get("environment") != "production", (
            "lazy-путь обязан уважать профиль окружения"
        )

    def test_explicit_environment_overrides_default(self) -> None:
        """Явный ``environment=`` — приоритетнее дефолта из settings."""
        import structlog

        init_application_logging(environment="staging")

        context = structlog.contextvars.get_contextvars()
        assert context.get("environment") == "staging"
