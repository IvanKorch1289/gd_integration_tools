"""S55 W1 — models.py part of cert_store decomp.

Classes: CertEntry.
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

import hashlib
from dataclasses import dataclass
from datetime import datetime

from src.backend.core.logging import get_logger

logger = get_logger("infrastructure.cert_store")


def _fingerprint(pem: str) -> str:
    """SHA-256 fingerprint от PEM (hex, lower)."""
    return hashlib.sha256(pem.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class CertEntry:
    """Запись сертификата в hot-cache / возвращаемый набор полей."""

    service_id: str
    pem: str
    fingerprint: str
    expires_at: datetime
    description: str | None = None
    version: int = 1
