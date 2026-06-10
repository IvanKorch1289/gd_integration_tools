"""S55 W1 — backend_memory.py part of cert_store decomp.

Classes: MemoryCertBackend.
"""
from __future__ import annotations

from src.backend.infrastructure.security.cert_store.backend_base import CertBackend

"""CertStore — хранилище TLS-сертификатов внешних сервисов (Wave 2.1).

Двухуровневая архитектура:

* **Backend** (persistent) — PEM сертификата + история. Реализации:

  * :class:`PostgresCertBackend` — таблицы ``certs`` + ``cert_history``;
  * :class:`VaultCertBackend` — HashiCorp Vault KV v2;
  * :class:`MongoCertBackend` — MongoDB-коллекция ``certs`` + ``certs_history``
    (lazy import ``pymongo``);
  * :class:`MemoryCertBackend` — in-process dict (тесты).

* **Hot cache** — in-process dict + опциональный Redis short-TTL кэш
  **fingerprint** (НЕ PEM). См. ``.claude/REDIS_AUDIT.md``.

Hot-reload механизм:

    set() → backend.save() → Redis Pub/Sub ``cert:updated`` → все инстансы
    инвалидируют локальный кэш. (Pub/Sub реализуется конкретными подписчиками
    через :meth:`subscribe_updates`.)

Пример::

    store = CertStore.from_settings(cert_store_settings)
    await store.set("skb_api", pem=PEM, expires_at=date(2027, 1, 1))
    pem = await store.get("skb_api")
"""

import asyncio
import hashlib
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from src.backend.core.config.cert_store import CertStoreSettings, cert_store_settings
from src.backend.infrastructure.database.models.cert import CertHistory, CertRecord
from src.backend.infrastructure.database.session_manager import main_session_manager
from src.backend.infrastructure.logging.factory import get_logger

logger = get_logger("infrastructure.cert_store")

@dataclass(slots=True)

class MemoryCertBackend(CertBackend):
    """In-process бэкенд (тесты, dev-стенд без БД)."""

    name = "memory"

    def __init__(self) -> None:
        self._data: dict[str, CertEntry] = {}
        self._history: list[CertEntry] = []

    async def get(self, service_id: str) -> CertEntry | None:
        return self._data.get(service_id)

    async def save(
        self,
        service_id: str,
        pem: str,
        expires_at: datetime,
        *,
        description: str | None = None,
        uploaded_by: str | None = None,
    ) -> CertEntry:
        prev = self._data.get(service_id)
        version = (prev.version + 1) if prev else 1
        entry = CertEntry(
            service_id=service_id,
            pem=pem,
            fingerprint=_fingerprint(pem),
            expires_at=expires_at,
            description=description,
            version=version,
        )
        self._data[service_id] = entry
        self._history.append(entry)
        return entry

    async def history(self, service_id: str) -> list[CertEntry]:
        return [e for e in self._history if e.service_id == service_id]

    async def list_expiring(self, before: datetime) -> list[CertEntry]:
        return [e for e in self._data.values() if e.expires_at <= before]

