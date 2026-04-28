"""Bootstrap для unit-тестов security / antivirus.

Pre-existing блокеры, которые здесь обходятся:

1. ``BaseSettingsWithLoader`` ищет ``config.yml`` через ``consts.ROOT_DIR``,
   а ``ROOT_DIR`` указывает на ``src/``. Подменяем на корень репозитория.
2. ``LoggerManager`` (singleton при импорте ``logging_service``) пытается
   подключиться к Graylog. Через env ``LOG_HOST=""`` отключаем graylog handler.
3. ``cert_store.py`` импортирует ``main_session_manager``, что тянет цепочку
   до ``psycopg2`` (который опционален и обычно не установлен в dev). Чтобы
   in-memory тесты ``MemoryCertBackend`` работали без БД, **до** импорта
   ``cert_store`` подменяем ``src.infrastructure.database.session_manager``
   и ``src.infrastructure.database.models.cert`` пустыми заглушками.

Эти стабы безопасны для unit-тестов: ``MemoryCertBackend`` и ``CertStore``
работают исключительно с in-process dict, ни одна из ORM-зависимостей не
вызывается.
"""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

# (1) ROOT_DIR -> корень репозитория, чтобы config.yml нашёлся.
from src.core.config.constants import consts

_REPO_ROOT = Path(__file__).resolve().parents[3]
if (_REPO_ROOT / "config.yml").exists():
    consts.ROOT_DIR = _REPO_ROOT

# (2) Отключаем graylog в LoggerManager до импорта settings.
os.environ.setdefault("LOG_HOST", "")
os.environ.setdefault("LOG_UDP_PORT", "1")

# (3) Стабим цепочку database/session_manager до того, как cert_store
#     попытается её импортировать. Заглушки имеют только те атрибуты,
#     которые читаются на module-level.
_session_mod_name = "src.infrastructure.database.session_manager"
if _session_mod_name not in sys.modules:
    _session_stub = types.ModuleType(_session_mod_name)
    _session_stub.main_session_manager = None  # type: ignore[attr-defined]
    sys.modules[_session_mod_name] = _session_stub

_cert_model_mod_name = "src.infrastructure.database.models.cert"
if _cert_model_mod_name not in sys.modules:
    _cert_model_stub = types.ModuleType(_cert_model_mod_name)
    _cert_model_stub.CertHistory = type("CertHistory", (), {})  # type: ignore[attr-defined]
    _cert_model_stub.CertRecord = type("CertRecord", (), {})  # type: ignore[attr-defined]
    sys.modules[_cert_model_mod_name] = _cert_model_stub
