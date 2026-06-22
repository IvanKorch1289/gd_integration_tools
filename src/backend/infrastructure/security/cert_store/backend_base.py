"""S55 W1 — backend_base.py part of cert_store decomp.

Classes: CertBackend.
"""

from __future__ import annotations

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

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from src.backend.core.logging import get_logger
from src.backend.infrastructure.security.cert_store.models import CertEntry

logger = get_logger("infrastructure.cert_store")


@dataclass(slots=True)
class CertBackend(ABC):
    """Контракт persistent-бэкенда сертификатов."""

    name: str = "base"

    @abstractmethod
    async def get(self, service_id: str) -> CertEntry | None: ...

    @abstractmethod
    async def save(
        self,
        service_id: str,
        pem: str,
        expires_at: datetime,
        *,
        description: str | None = None,
        uploaded_by: str | None = None,
    ) -> CertEntry: ...

    @abstractmethod
    async def history(self, service_id: str) -> list[CertEntry]: ...

    @abstractmethod
    async def list_expiring(self, before: datetime) -> list[CertEntry]: ...
