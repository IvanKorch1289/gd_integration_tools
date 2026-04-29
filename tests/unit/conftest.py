"""Общий bootstrap для всех unit-тестов.

Решает pre-existing блокеры тестовой инфраструктуры, которые иначе пришлось
бы дублировать в каждом подкаталоге:

1. ``BaseSettingsWithLoader`` ищет ``config_profiles/`` через
   ``consts.ROOT_DIR``, а по умолчанию ``ROOT_DIR`` указывает на ``src/``.
   Подменяем на ближайший каталог-предок с ``pyproject.toml``
   (worktree-safe). Также подгружаем ``.env`` оттуда, если он есть.
2. ``LoggerManager`` (singleton при импорте ``logging_service``) пытается
   подключиться к Graylog. Через env ``LOG_HOST=""`` отключаем graylog
   handler — :meth:`GraylogHandler.enabled` возвращает False.
3. Дефолты для обязательных env-vars (REDIS_* / MAIL_* / QUEUE_* / FS_*) —
   на случай отсутствия ``.env`` в worktree-копии. ``setdefault`` уважает
   реальные значения и срабатывает только как fallback.

Подкаталоговые ``conftest.py`` выполняются ПОСЛЕ этого файла и могут
дополнять его специфичными частями (например, security-стабы для
``cert_store`` или Python-2 syntax patcher для DSL).
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from src.core.config.constants import consts


def _find_repo_root_with_config() -> Path | None:
    """Найти ближайший каталог-предок, содержащий ``pyproject.toml``.

    Anchor — ``pyproject.toml``: единственный файл, гарантированно
    лежащий в корне репозитория. Каталог ``config_profiles/`` рядом с
    ним содержит загружаемые YAML-настройки.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return None


# (1) ROOT_DIR -> корень репо.
_REPO_ROOT = _find_repo_root_with_config()
if _REPO_ROOT is not None:
    consts.ROOT_DIR = _REPO_ROOT
    env_file = _REPO_ROOT / ".env"
    if env_file.exists():
        load_dotenv(env_file)

# (2) Отключаем graylog в LoggerManager до импорта logger-модулей.
os.environ.setdefault("LOG_HOST", "")
os.environ.setdefault("LOG_UDP_PORT", "1")

# (3) Безопасные fallback-дефолты для обязательных env-vars. ``setdefault``
# не перезатирает реальные значения из ``.env`` или CI-конфига.
# Redis (см. src/core/config/services/cache.py:RedisSettings).
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("REDIS_DB", "0")
os.environ.setdefault("REDIS_PASSWORD", "")
# Mail (см. src/core/config/services/mail.py:MailSettings) — host/port в YAML,
# username/password — секреты.
os.environ.setdefault("MAIL_USERNAME", "")
os.environ.setdefault("MAIL_PASSWORD", "")
# Queue (см. src/core/config/services/queue.py:QueueSettings).
os.environ.setdefault("QUEUE_USERNAME", "")
os.environ.setdefault("QUEUE_PASSWORD", "")
# File-storage (см. src/core/config/services/storage.py).
os.environ.setdefault("FS_ACCESS_KEY", "")
os.environ.setdefault("FS_SECRET_KEY", "")
