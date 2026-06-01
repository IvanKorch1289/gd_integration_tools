"""Banking-namespace conftest: env-vars fallback для worktree без .env.

Wave ``[wave:s6/k3-banking-processors-tests]``.

В worktree без ``.env`` импорт DSL-процессоров триггерит загрузку
``DatabaseConnectionSettings`` / ``DadataAPISettings`` через side-effect
импорт в module-loader, что приводит к ValidationError.

Решение: подмена fallback-значений через ``os.environ.setdefault``
ДО первого импорта процессоров. ``setdefault`` уважает реальный ``.env``
в master-worktree (значения уже загружены).
"""

from __future__ import annotations

import os

# Дефолты для обязательных env-vars — требуются validate_required_fields
# в DatabaseConnectionSettings/MongoConnectionSettings/SecureSettings/etc.
# Достаточно установить минимально валидные значения; реальные тесты
# не дёргают БД/Mongo/Dadata.
os.environ.setdefault("DB_USERNAME", "test_user")
os.environ.setdefault("DB_PASSWORD", "test_password_123")
os.environ.setdefault("MONGO_USERNAME", "mongo_user")
os.environ.setdefault("MONGO_PASSWORD", "mongo_password_123")
os.environ.setdefault("DADATA_API_KEY", "0" * 40)
os.environ.setdefault("SKB_API_KEY", "0" * 40)
os.environ.setdefault("SECRET_KEY", "0" * 64)
os.environ.setdefault("API_KEY", "0" * 64)
os.environ.setdefault("SEC_SECRET_KEY", "0" * 64)
os.environ.setdefault("SEC_API_KEY", "0" * 64)
