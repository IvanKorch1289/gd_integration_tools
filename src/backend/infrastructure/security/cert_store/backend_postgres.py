"""S55 W1 — backend_postgres.py part of cert_store decomp.

Classes: PostgresCertBackend.
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

from sqlalchemy import select

from src.backend.core.domain.models.cert import CertHistory, CertRecord
from src.backend.core.logging import get_logger
from src.backend.infrastructure.database.session_manager import main_session_manager
from src.backend.infrastructure.security.cert_store.models import (
    CertEntry,
    _fingerprint,
)

logger = get_logger("infrastructure.cert_store")


@dataclass(slots=True)
class PostgresCertBackend(CertBackend):
    """PostgreSQL бэкенд: таблицы ``certs`` + ``cert_history``."""

    name = "postgres"

    async def get(self, service_id: str) -> CertEntry | None:
        async with main_session_manager.create_session() as session:
            row = (
                await session.execute(
                    select(CertRecord).where(CertRecord.service_id == service_id)
                )
            ).scalar_one_or_none()
        return self._to_entry(row) if row else None

    async def save(
        self,
        service_id: str,
        pem: str,
        expires_at: datetime,
        *,
        description: str | None = None,
        uploaded_by: str | None = None,
    ) -> CertEntry:
        """Сохраняет сертификат (upsert) в PostgreSQL с инкрементом версии."""
        fp = _fingerprint(pem)
        async with main_session_manager.create_session() as session:
            async with main_session_manager.transaction(session):
                existing = (
                    await session.execute(
                        select(CertRecord).where(CertRecord.service_id == service_id)
                    )
                ).scalar_one_or_none()
                version = (existing.version + 1) if existing else 1

                if existing:
                    existing.pem = pem
                    existing.fingerprint = fp
                    existing.expires_at = expires_at
                    existing.description = description
                    existing.version = version
                else:
                    session.add(
                        CertRecord(
                            service_id=service_id,
                            pem=pem,
                            fingerprint=fp,
                            expires_at=expires_at,
                            description=description,
                            version=version,
                        )
                    )

                session.add(
                    CertHistory(
                        service_id=service_id,
                        version=version,
                        pem=pem,
                        uploaded_by=uploaded_by,
                    )
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
        async with main_session_manager.create_session() as session:
            rows = (
                (
                    await session.execute(
                        select(CertHistory)
                        .where(CertHistory.service_id == service_id)
                        .order_by(CertHistory.version.asc())
                    )
                )
                .scalars()
                .all()
            )
        return [
            CertEntry(
                service_id=r.service_id,
                pem=r.pem,
                fingerprint=_fingerprint(r.pem),
                expires_at=datetime.now(tz=UTC),  # история без expires
                description=None,
                version=r.version,
            )
            for r in rows
        ]

    async def list_expiring(self, before: datetime) -> list[CertEntry]:
        async with main_session_manager.create_session() as session:
            rows = (
                (
                    await session.execute(
                        select(CertRecord).where(CertRecord.expires_at <= before)
                    )
                )
                .scalars()
                .all()
            )
        return [self._to_entry(r) for r in rows]

    @staticmethod
    def _to_entry(row: CertRecord) -> CertEntry:
        return CertEntry(
            service_id=row.service_id,
            pem=row.pem,
            fingerprint=row.fingerprint,
            expires_at=row.expires_at,
            description=row.description,
            version=row.version,
        )
