"""Bootstrap для unit-тестов Express HTTP-клиента.

Решает pre-existing проблемы тестовой инфраструктуры:

1. ``BaseSettingsWithLoader`` ищет ``config.yml`` через ``consts.ROOT_DIR``,
   а по умолчанию ``ROOT_DIR`` указывает на ``src/``. Подменяем на корень
   репозитория, чтобы settings корректно подгружали ``config.yml``.
2. ``LoggerManager`` (singleton при импорте) пытается подключиться к
   Graylog через ``graypy``. Через env ``LOG_HOST=""`` отключаем graylog
   handler.
"""

from __future__ import annotations

import os
from pathlib import Path

# Глубина: tests/unit/express/conftest.py -> parents[3] == корень репозитория.
from src.core.config.constants import consts

_REPO_ROOT = Path(__file__).resolve().parents[3]
if (_REPO_ROOT / "config.yml").exists():
    consts.ROOT_DIR = _REPO_ROOT

os.environ.setdefault("LOG_HOST", "")
os.environ.setdefault("LOG_UDP_PORT", "1")
