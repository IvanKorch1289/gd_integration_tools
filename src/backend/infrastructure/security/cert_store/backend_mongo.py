"""S55 W1 — backend_mongo.py part of cert_store decomp.

Classes: MongoCertBackend.
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

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.infrastructure.security.cert_store.models import (
    CertEntry,
    _fingerprint,
)

logger = get_logger("infrastructure.cert_store")


@dataclass
class MongoCertBackend(CertBackend):
    """MongoDB бэкенд: коллекции ``certs`` + ``certs_history``.

    Использует ``pymongo.AsyncMongoClient`` (нативный async API,
    pymongo>=4.9). Если ``pymongo`` не установлен — поднимает
    ``RuntimeError`` при первом обращении.

    Документ ``certs``::

        {
            "_id": <service_id>,
            "pem": <str>,
            "fingerprint": <str>,
            "expires_at": <datetime>,
            "description": <str|None>,
            "version": <int>,
        }

    Документ ``certs_history``::

        {
            "service_id": <str>,
            "version": <int>,
            "pem": <str>,
            "uploaded_by": <str|None>,
            "created_at": <datetime>,
        }
    """

    name = "mongo"

    def __init__(self, collection_name: str = "certs") -> None:
        self._collection_name = collection_name
        self._history_collection_name = f"{collection_name}_history"
        self._client: Any | None = None

    def _db(self) -> Any:
        """Лениво создаёт клиент и возвращает Database."""
        if self._client is None:
            try:
                from pymongo import AsyncMongoClient
            except ImportError as exc:
                raise RuntimeError(
                    "MongoCertBackend требует пакет 'pymongo>=4.9'. "
                    "Установите: uv add pymongo>=4.9"
                ) from exc

            from src.backend.core.config.mongo import mongo_connection_settings as cfg

            self._client = AsyncMongoClient(
                cfg.connection_string,
                minPoolSize=cfg.min_pool_size,
                maxPoolSize=cfg.max_pool_size,
                serverSelectionTimeoutMS=cfg.timeout,
            )
            self._db_name = cfg.name
        return self._client[self._db_name]

    async def get(self, service_id: str) -> CertEntry | None:
        coll = self._db()[self._collection_name]
        doc = await coll.find_one({"_id": service_id})
        if doc is None:
            return None
        return CertEntry(
            service_id=service_id,
            pem=doc["pem"],
            fingerprint=doc.get("fingerprint", _fingerprint(doc["pem"])),
            expires_at=doc["expires_at"],
            description=doc.get("description"),
            version=int(doc.get("version", 1)),
        )

    async def save(
        self,
        service_id: str,
        pem: str,
        expires_at: datetime,
        *,
        description: str | None = None,
        uploaded_by: str | None = None,
    ) -> CertEntry:
        fp = _fingerprint(pem)
        db = self._db()
        coll = db[self._collection_name]
        history = db[self._history_collection_name]

        prev = await coll.find_one({"_id": service_id})
        version = (int(prev["version"]) + 1) if prev else 1

        doc = {
            "_id": service_id,
            "pem": pem,
            "fingerprint": fp,
            "expires_at": expires_at,
            "description": description,
            "version": version,
        }
        await coll.replace_one({"_id": service_id}, doc, upsert=True)
        await history.insert_one(
            {
                "service_id": service_id,
                "version": version,
                "pem": pem,
                "uploaded_by": uploaded_by,
                "created_at": datetime.now(tz=UTC),
            }
        )
        return CertEntry(
            service_id=service_id,
            pem=pem,
            fingerprint=fp,
            expires_at=expires_at,
            description=description,
            version=version,
        )

    async def history(self, service_id: str) -> list[CertEntry]:
        coll = self._db()[self._history_collection_name]
        cursor = coll.find({"service_id": service_id}).sort("version", 1)
        result: list[CertEntry] = []
        async for doc in cursor:
            result.append(
                CertEntry(
                    service_id=doc["service_id"],
                    pem=doc["pem"],
                    fingerprint=_fingerprint(doc["pem"]),
                    expires_at=doc.get("created_at", datetime.now(tz=UTC)),
                    description=None,
                    version=int(doc["version"]),
                )
            )
        return result

    async def list_expiring(self, before: datetime) -> list[CertEntry]:
        coll = self._db()[self._collection_name]
        cursor = coll.find({"expires_at": {"$lte": before}})
        result: list[CertEntry] = []
        async for doc in cursor:
            result.append(
                CertEntry(
                    service_id=doc["_id"],
                    pem=doc["pem"],
                    fingerprint=doc.get("fingerprint", _fingerprint(doc["pem"])),
                    expires_at=doc["expires_at"],
                    description=doc.get("description"),
                    version=int(doc.get("version", 1)),
                )
            )
        return result
