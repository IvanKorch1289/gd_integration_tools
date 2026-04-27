"""CertStore — хранилище TLS-сертификатов внешних сервисов (Wave 2.1).

Двухуровневая архитектура:

* **Backend** (persistent) — PEM сертификата + история. Реализации:

  * :class:`PostgresCertBackend` — таблицы ``certs`` + ``cert_history``;
  * :class:`VaultCertBackend` — HashiCorp Vault KV v2;
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

from __future__ import annotations

import asyncio
import hashlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Awaitable, Callable

from sqlalchemy import select

from src.core.config.cert_store import CertStoreSettings, cert_store_settings
from src.infrastructure.database.models.cert import CertHistory, CertRecord
from src.infrastructure.database.session_manager import main_session_manager

__all__ = (
    "CertStore",
    "CertEntry",
    "CertBackend",
    "MemoryCertBackend",
    "PostgresCertBackend",
    "VaultCertBackend",
    "create_cert_store",
)

logger = logging.getLogger("infrastructure.cert_store")


@dataclass(slots=True)
class CertEntry:
    """Запись сертификата в hot-cache / возвращаемый набор полей."""

    service_id: str
    pem: str
    fingerprint: str
    expires_at: datetime
    description: str | None = None
    version: int = 1


def _fingerprint(pem: str) -> str:
    """SHA-256 fingerprint от PEM (hex, lower)."""
    return hashlib.sha256(pem.encode("utf-8")).hexdigest()


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


# ────────────────── In-memory backend (тесты) ──────────────────


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


# ────────────────── PostgreSQL backend ──────────────────


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
        fp = _fingerprint(pem)
        async with main_session_manager.create_session() as session:
            async with main_session_manager.transaction(session):
                existing = (
                    await session.execute(
                        select(CertRecord).where(
                            CertRecord.service_id == service_id
                        )
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
                await session.execute(
                    select(CertHistory)
                    .where(CertHistory.service_id == service_id)
                    .order_by(CertHistory.version.asc())
                )
            ).scalars().all()
        return [
            CertEntry(
                service_id=r.service_id,
                pem=r.pem,
                fingerprint=_fingerprint(r.pem),
                expires_at=datetime.now(tz=timezone.utc),  # история без expires
                description=None,
                version=r.version,
            )
            for r in rows
        ]

    async def list_expiring(self, before: datetime) -> list[CertEntry]:
        async with main_session_manager.create_session() as session:
            rows = (
                await session.execute(
                    select(CertRecord).where(CertRecord.expires_at <= before)
                )
            ).scalars().all()
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


# ────────────────── Vault backend ──────────────────


class VaultCertBackend(CertBackend):
    """HashiCorp Vault KV v2 бэкенд (prod-рекомендация).

    Каждому ``service_id`` соответствует путь ``{base_path}/{service_id}``
    с полями ``pem``, ``fingerprint``, ``expires_at``, ``description``,
    ``version``. История ведётся на стороне Vault (KV v2 хранит revisions).
    """

    name = "vault"

    def __init__(self, base_path: str) -> None:
        self._base = base_path.rstrip("/")
        self._client_factory: Callable[[], Any] | None = None

    def _client(self) -> Any:
        from hvac import Client  # лениво, чтобы тесты без Vault работали

        from src.core.config.settings import settings

        url = getattr(settings, "vault_url", None) or getattr(
            settings.app, "vault_url", None
        )
        token = getattr(settings, "vault_token", None) or getattr(
            settings.app, "vault_token", None
        )
        client = Client(url=url, token=token)
        if not client.is_authenticated():
            raise ConnectionError("Vault: не аутентифицирован")
        return client

    async def get(self, service_id: str) -> CertEntry | None:
        loop = asyncio.get_event_loop()
        try:
            client = self._client()
            data = await loop.run_in_executor(
                None,
                lambda: client.secrets.kv.v2.read_secret_version(
                    path=f"{self._base}/{service_id}"
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Vault read failed for %s: %s", service_id, exc)
            return None
        secret = (data or {}).get("data", {}).get("data") or {}
        if not secret:
            return None
        return CertEntry(
            service_id=service_id,
            pem=secret["pem"],
            fingerprint=secret.get("fingerprint", _fingerprint(secret["pem"])),
            expires_at=datetime.fromisoformat(secret["expires_at"]),
            description=secret.get("description"),
            version=int(secret.get("version", 1)),
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
        prev = await self.get(service_id)
        version = (prev.version + 1) if prev else 1
        fp = _fingerprint(pem)
        secret = {
            "pem": pem,
            "fingerprint": fp,
            "expires_at": expires_at.isoformat(),
            "description": description or "",
            "version": version,
            "uploaded_by": uploaded_by or "",
        }
        loop = asyncio.get_event_loop()
        client = self._client()
        await loop.run_in_executor(
            None,
            lambda: client.secrets.kv.v2.create_or_update_secret(
                path=f"{self._base}/{service_id}", secret=secret
            ),
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
        # Vault KV v2 хранит revisions; полная реализация требует обхода
        # versions API — для baseline возвращаем последнюю.
        last = await self.get(service_id)
        return [last] if last else []

    async def list_expiring(self, before: datetime) -> list[CertEntry]:
        # Поиск по всем сертификатам в Vault через list — отдельный flow,
        # нужен только для admin-задач. Baseline — пустой результат.
        return []


# ────────────────── Frontend ──────────────────


class CertStore:
    """Высокоуровневый фасад: backend + in-process кэш + hooks.

    Hot-reload: подписчики через :meth:`subscribe_updates` уведомляются
    после ``set()``. Конкретный транспорт (Redis Pub/Sub, локальный broadcast)
    реализуется вызывающей стороной.
    """

    def __init__(self, backend: CertBackend, settings: CertStoreSettings) -> None:
        self._backend = backend
        self._settings = settings
        self._cache: dict[str, CertEntry] = {}
        self._listeners: list[Callable[[str], Awaitable[None] | None]] = []

    @classmethod
    def from_settings(cls, settings: CertStoreSettings) -> "CertStore":
        backend: CertBackend
        match settings.backend:
            case "vault":
                backend = VaultCertBackend(base_path=settings.vault_path)
            case "memory":
                backend = MemoryCertBackend()
            case _:
                backend = PostgresCertBackend()
        return cls(backend=backend, settings=settings)

    async def get(self, service_id: str) -> str | None:
        cached = self._cache.get(service_id)
        if cached:
            return cached.pem
        entry = await self._backend.get(service_id)
        if entry:
            self._cache[service_id] = entry
            return entry.pem
        return None

    async def get_entry(self, service_id: str) -> CertEntry | None:
        cached = self._cache.get(service_id)
        if cached:
            return cached
        entry = await self._backend.get(service_id)
        if entry:
            self._cache[service_id] = entry
        return entry

    async def set(
        self,
        service_id: str,
        pem: str,
        expires_at: datetime,
        *,
        description: str | None = None,
        uploaded_by: str | None = None,
    ) -> CertEntry:
        entry = await self._backend.save(
            service_id,
            pem,
            expires_at,
            description=description,
            uploaded_by=uploaded_by,
        )
        self._cache[service_id] = entry
        await self._notify(service_id)
        return entry

    async def history(self, service_id: str) -> list[CertEntry]:
        return await self._backend.history(service_id)

    async def get_expiring_soon(self) -> list[CertEntry]:
        deadline = datetime.now(tz=timezone.utc) + timedelta(
            days=self._settings.expire_warn_days
        )
        return await self._backend.list_expiring(deadline)

    def invalidate(self, service_id: str) -> None:
        """Сбрасывает кэш одного сервиса (вызывается обработчиком pub/sub)."""
        self._cache.pop(service_id, None)

    def subscribe_updates(
        self, listener: Callable[[str], Awaitable[None] | None]
    ) -> None:
        """Подписаться на событие ``cert:updated`` (получит ``service_id``)."""
        self._listeners.append(listener)

    async def _notify(self, service_id: str) -> None:
        for listener in list(self._listeners):
            try:
                result = listener(service_id)
                if isinstance(result, AsyncIterator):  # pragma: no cover
                    continue
                if hasattr(result, "__await__"):
                    await result  # type: ignore[func-returns-value]
            except Exception as exc:  # noqa: BLE001
                logger.warning("CertStore listener failed: %s", exc)


def create_cert_store() -> CertStore:
    """Фабрика по умолчанию — собирает store из глобальных настроек."""
    return CertStore.from_settings(cert_store_settings)
