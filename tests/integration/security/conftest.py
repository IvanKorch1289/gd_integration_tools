"""Bootstrap для интеграционных тестов CertStore.

Решает две pre-existing проблемы тестовой инфраструктуры:

1. ``BaseSettingsWithLoader`` ищет ``config_profiles/`` через
   ``consts.ROOT_DIR``, а ``ROOT_DIR`` указывает на ``src/``. Подменяем
   на корень репозитория (anchor — ``pyproject.toml``).
2. ``LoggerManager`` (singleton при импорте ``logging_service``) пытается
   подключиться к Graylog, что тянет ``graypy`` (опциональный пакет, не
   установленный в dev-зависимостях). Через env ``LOG_HOST=""`` отключаем
   graylog handler — :meth:`GraylogHandler.enabled` возвращает False.
"""

from __future__ import annotations

import os
from pathlib import Path

# (1) ROOT_DIR → корень репозитория, чтобы config_profiles/ нашёлся.
from src.core.config.constants import consts

_REPO_ROOT = Path(__file__).resolve().parents[3]
if (_REPO_ROOT / "pyproject.toml").is_file():
    consts.ROOT_DIR = _REPO_ROOT

# (2) Отключаем graylog в LoggerManager до импорта settings.
os.environ.setdefault("LOG_HOST", "")
os.environ.setdefault("LOG_UDP_PORT", "1")
