"""Профили запуска приложения (W21.1).

Профиль выбирается через переменную окружения ``APP_PROFILE`` и определяет,
какие бэкенды используются: лёгкие локальные аналоги (dev_light) или полный
production-стек (prod). Используется как ключ overlay-файла для
``config_profiles/{profile}.yml`` в :mod:`src.core.config.config_loader`.
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Final

__all__ = (
    "APP_PROFILE_ENV",
    "DEFAULT_PROFILE",
    "AppProfileChoices",
    "get_active_profile",
)


APP_PROFILE_ENV: Final[str] = "APP_PROFILE"


class AppProfileChoices(str, Enum):
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

    Если переменная не задана или содержит неизвестное значение,
    возвращает :data:`DEFAULT_PROFILE`. Регистр значения игнорируется.
    """
    raw = os.environ.get(APP_PROFILE_ENV, "").strip().lower()
    if not raw:
        return DEFAULT_PROFILE
    try:
        return AppProfileChoices(raw)
    except ValueError:
        return DEFAULT_PROFILE
