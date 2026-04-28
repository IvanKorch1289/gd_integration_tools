"""Bootstrap для unit-тестов DSL Wave 11 (audit + scan_file).

Решает pre-existing проблемы тестовой инфраструктуры:

1. ``BaseSettingsWithLoader`` ищет ``config.yml`` через ``consts.ROOT_DIR``,
   а ``ROOT_DIR`` указывает на ``src/``. Подменяем на корень репозитория.
2. ``LoggerManager`` (singleton при импорте ``logging_service``) пытается
   подключиться к Graylog — отключаем через ``LOG_HOST=""``.
3. Lazy-импорты ``ImmutableAuditStore`` / ``create_antivirus_backend`` /
   ``s3_client`` тянут redis settings — мокаются в самих тестах через
   ``patch`` на module-level импорт, поэтому здесь только базовые env-vars.
"""

from __future__ import annotations

import os
from pathlib import Path

# (1) ROOT_DIR -> корень репо. Глубина: tests/unit/dsl/wave11/conftest.py = parents[4]
from src.core.config.constants import consts

_REPO_ROOT = Path(__file__).resolve().parents[4]
if (_REPO_ROOT / "config.yml").exists():
    consts.ROOT_DIR = _REPO_ROOT

# (2) Отключаем graylog в LoggerManager до импорта settings.
os.environ.setdefault("LOG_HOST", "")
os.environ.setdefault("LOG_UDP_PORT", "1")

# (3) Минимальные REDIS_* env-vars — на случай, если какие-то lazy импорты
# в audit/scan_file/antivirus стянут cache settings раньше, чем тест успеет
# их замокать.
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("REDIS_DB", "0")
os.environ.setdefault("REDIS_PASSWORD", "")
