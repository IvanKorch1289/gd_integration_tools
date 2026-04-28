"""Bootstrap для unit-тестов notebooks.

Решает pre-existing проблемы тестовой инфраструктуры:

1. ``BaseSettingsWithLoader`` ищет ``config.yml`` через ``consts.ROOT_DIR``;
   по умолчанию ``ROOT_DIR`` указывает на ``src/``. Подменяем на корень репозитория.
2. ``LoggerManager`` (singleton при импорте ``logging_service``) пытается
   подключиться к Graylog. Через ``LOG_HOST=""`` отключаем graylog handler.

Notebooks-сервис не цепляет Redis при импорте (используется ленивый
``MongoNotebookRepository`` с fallback на InMemory), поэтому REDIS_*-env
для unit-уровня не требуется.
"""

from __future__ import annotations

import os
from pathlib import Path

# (1) ROOT_DIR → корень репозитория, чтобы config.yml нашёлся.
from src.core.config.constants import consts

_REPO_ROOT = Path(__file__).resolve().parents[3]
if (_REPO_ROOT / "config.yml").exists():
    consts.ROOT_DIR = _REPO_ROOT

# (2) Отключаем graylog в LoggerManager.
os.environ.setdefault("LOG_HOST", "")
os.environ.setdefault("LOG_UDP_PORT", "1")
