"""Bootstrap для unit-тестов security / antivirus.

Общий env-bootstrap (ROOT_DIR / LOG_HOST / fallback env-vars) вынесен в
``tests/unit/conftest.py``. Здесь — только специфичные стабы:

``cert_store.py`` импортирует ``main_session_manager``, что тянет цепочку
до ``psycopg2`` (опционален, обычно не установлен в dev). Для in-memory
тестов ``MemoryCertBackend`` подменяем ``session_manager`` и
``models.cert`` пустыми заглушками до их первого импорта.

Эти стабы безопасны для unit-тестов: ``MemoryCertBackend`` и ``CertStore``
работают исключительно с in-process dict, ни одна из ORM-зависимостей не
вызывается.
"""

from __future__ import annotations

import sys
import types

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
