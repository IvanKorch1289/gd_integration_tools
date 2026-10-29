"""Профили запуска приложения (W21.1).

Профиль выбирается через переменную окружения ``APP_PROFILE`` и определяет,
какие бэкенды используются: лёгкие локальные аналоги (dev_light) или полный
production-стек (prod). Используется как ключ overlay-файла для
``config_profiles/{profile}.yml`` в :mod:`src.core.config.config_loader`.

ADR-0379: неизвестное значение ``APP_PROFILE`` — ошибка конфигурации
(fail-closed, ``ValueError``), а не молчаливый откат на ``dev``
(fail-open с ``app.debug_mode=True``).
"""

from __future__ import annotations

import os
from enum import StrEnum
from typing import Any, Final

__all__ = (
    "APP_PROFILE_ENV",
    "DEFAULT_PROFILE",
    "AppProfileChoices",
    "get_active_profile",
)


APP_PROFILE_ENV: Final[str] = "APP_PROFILE"


def _logger() -> Any:
    """Ленивый логгер (избегает циклического импорта).

    ``core.logging`` → ``infrastructure.logging.factory`` →
    ``core.config.profile`` — импорт логгера на уровне модуля замкнул бы
    цикл (профиль импортируется из ``config_loader`` на верхнем уровне).

    Returns:
        Экземпляр логгера проекта.

    """
    from src.backend.core.logging import get_logger

    return get_logger(__name__)


class AppProfileChoices(StrEnum):
    """Допустимые профили запуска приложения.

    Значения:
        dev_light: лёгкий локальный профиль без Docker
            (SQLite/cachetools/LocalFS вместо PG/Redis/S3).
        dev: полная dev-среда с локальной инфраструктурой.
        staging: предпродакшн-окружение.
        prod: production.
    """

    dev_light = "dev_light"
    dev = "dev"
    staging = "staging"
    prod = "prod"


DEFAULT_PROFILE: Final[AppProfileChoices] = AppProfileChoices.dev


def get_active_profile() -> AppProfileChoices:
    """Возвращает активный профиль из ``APP_PROFILE``.

    Пустое/незаданное значение → :data:`DEFAULT_PROFILE`. Регистр
    значения игнорируется.

    ADR-0379: НЕИЗВЕСТНОЕ значение (опечатка, например ``prodd``) —
    это ошибка конфигурации, а не повод молча включить ``dev``
    (fail-open: ``app.debug_mode=True`` из ``dev.yml``). Значение
    отвергается с ``ValueError`` (fail-closed): приложение не стартует
    с неверным профилем, оператор видит причину сразу.

    Returns:
        Активный профиль приложения.

    Raises:
        ValueError: Если ``APP_PROFILE`` содержит неизвестное значение.

    """
    raw = os.environ.get(APP_PROFILE_ENV, "").strip().lower()
    if not raw:
        return DEFAULT_PROFILE
    try:
        return AppProfileChoices(raw)
    except ValueError:
        allowed = ", ".join(profile.value for profile in AppProfileChoices)
        message = (
            f"{APP_PROFILE_ENV}={raw!r} — неизвестный профиль. "
            f"Допустимые значения: {allowed}"
        )
        _logger().warning(message)
        raise ValueError(message) from None
