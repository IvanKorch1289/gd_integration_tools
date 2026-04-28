"""Bootstrap для unit-тестов cache backends.

Решает pre-existing проблемы тестовой инфраструктуры:

1. ``BaseSettingsWithLoader`` ищет ``config.yml`` через ``consts.ROOT_DIR``,
   а по умолчанию ``ROOT_DIR`` указывает на ``src/``. Ищем ближайший
   каталог-предок с ``config.yml`` и подменяем ROOT_DIR. Также явно
   подгружаем ``.env`` оттуда (если есть), чтобы pydantic-settings
   получил MAIL_*/QUEUE_*/FS_*/REDIS_* секреты.
2. ``LoggerManager`` (singleton при импорте ``logging_service``) пытается
   подключиться к Graylog. Через env ``LOG_HOST=""`` отключаем graylog
   handler — :meth:`GraylogHandler.enabled` возвращает False.
3. На случай если ``.env``/``config.yml`` не найдены — даём дефолты для
   обязательных REDIS_*/MAIL_*/QUEUE_*/FS_* env-vars (минимально для
   успешной инстанциации settings на module-level в
   ``src/core/config/services/__init__.py``).
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# (1) ROOT_DIR -> ближайший каталог с ``config.yml``. В worktree-копии
# репозитория config.yml лежит на 4 уровня выше; в обычном чекауте — на
# 3 уровня. Идём по родителям, чтобы найти и обычный, и worktree-кейс.
from src.core.config.constants import consts


def _find_repo_root_with_config() -> Path | None:
    """Найти ближайший каталог-предок, содержащий ``config.yml``."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "config.yml").exists():
            return parent
    return None


_REPO_ROOT = _find_repo_root_with_config()
if _REPO_ROOT is not None:
    consts.ROOT_DIR = _REPO_ROOT
    # Подгружаем .env вручную, т.к. ``config_loader.load_dotenv`` уже мог
    # отработать на старом ROOT_DIR (который указывал на ``src/``).
    env_file = _REPO_ROOT / ".env"
    if env_file.exists():
        load_dotenv(env_file)

# (2) Отключаем graylog в LoggerManager до импорта logger-модулей.
os.environ.setdefault("LOG_HOST", "")
os.environ.setdefault("LOG_UDP_PORT", "1")

# (3) Дефолты для обязательных env-vars — на случай отсутствия .env в
# worktree-копии (там нет .env, но есть config.yml через симлинк).
# Pydantic читает env > yaml, поэтому setdefault даёт безопасные fallback.
# Redis (см. src/core/config/services/cache.py:RedisSettings).
os.environ.setdefault("REDIS_PASSWORD", "")
# Mail (см. src/core/config/services/mail.py:MailSettings) — host/port
# и прочее задано в config.yml; username/password — секреты.
os.environ.setdefault("MAIL_USERNAME", "")
os.environ.setdefault("MAIL_PASSWORD", "")
# Queue (см. src/core/config/services/queue.py:QueueSettings).
os.environ.setdefault("QUEUE_USERNAME", "")
os.environ.setdefault("QUEUE_PASSWORD", "")
# File-storage (см. src/core/config/services/storage.py).
os.environ.setdefault("FS_ACCESS_KEY", "")
os.environ.setdefault("FS_SECRET_KEY", "")
