"""Bootstrap для unit-тестов внешних клиентов.

Решает pre-existing проблемы тестовой инфраструктуры:

1. ``BaseSettingsWithLoader`` ищет ``config.yml`` через ``consts.ROOT_DIR``;
   по умолчанию ``ROOT_DIR`` указывает на ``src/``. Подменяем на корень репозитория.
2. ``LoggerManager`` пытается подключиться к Graylog — отключаем через ``LOG_HOST``.

``BaseExternalAPIClient`` импортирует ``HttpClient`` из
``src/infrastructure/clients/transport/http.py``; ``HttpClient`` использует
``http_base_settings`` (yaml) — это покрывается восстановлением ROOT_DIR.
Прямого обращения к Redis при импорте нет, REDIS_*-env не требуется.
"""

from __future__ import annotations

import os
from pathlib import Path

from src.core.config.constants import consts

_REPO_ROOT = Path(__file__).resolve().parents[3]
if (_REPO_ROOT / "config.yml").exists():
    consts.ROOT_DIR = _REPO_ROOT

os.environ.setdefault("LOG_HOST", "")
os.environ.setdefault("LOG_UDP_PORT", "1")
