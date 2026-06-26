"""S55 W1 — store.py part of cert_store decomp.

Classes: CertStore.
"""

from __future__ import annotations

from src.backend.infrastructure.security.cert_store.backend_base import CertBackend
from src.backend.infrastructure.security.cert_store.backend_memory import (
    MemoryCertBackend,
)
from src.backend.infrastructure.security.cert_store.backend_mongo import (
    MongoCertBackend,
)
from src.backend.infrastructure.security.cert_store.backend_postgres import (
    PostgresCertBackend,
)
from src.backend.infrastructure.security.cert_store.backend_vault import (
    VaultCertBackend,
)

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

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from src.backend.core.config.cert_store import CertStoreSettings
from src.backend.core.logging import get_logger
from src.backend.infrastructure.security.cert_store.models import CertEntry

logger = get_logger("infrastructure.cert_store")


@dataclass
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
    def from_settings(cls, settings: CertStoreSettings) -> CertStore:
        """Create CertStore from settings.

        Args:
            settings: Certificate store settings.

        Returns:
            Configured CertStore instance.
        """
        backend: CertBackend
        match settings.backend:
            case "vault":
                backend = VaultCertBackend(base_path=settings.vault_path)
            case "mongo":
                backend = MongoCertBackend(collection_name=settings.mongo_collection)
            case "memory":
                backend = MemoryCertBackend()
            case "consul":
                from src.backend.infrastructure.security.cert_store.backend_consul import (
                    ConsulCertBackend,
                )

                backend = ConsulCertBackend(base_path=settings.vault_path)
            case _:
                backend = PostgresCertBackend()
        instance = cls(backend=backend, settings=settings)
        # S171 M16 (D245): auto-start file watcher при watch_enabled=True.
        # Прописан lazy — чтобы не запускать в unit-тестах.
        # Production: register в lifespan startup.
        return instance

    async def get(self, service_id: str) -> str | None:
        """Get PEM certificate for a service.

        Args:
            service_id: Service identifier.

        Returns:
            PEM string or None if not found.
        """
        cached = self._cache.get(service_id)
        if cached:
            return cached.pem
        entry = await self._backend.get(service_id)
        if entry:
            self._cache[service_id] = entry
            return entry.pem
        return None

    async def get_entry(self, service_id: str) -> CertEntry | None:
        """Get full certificate entry for a service.

        Args:
            service_id: Service identifier.

        Returns:
            CertEntry or None if not found.
        """
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
        """Store a certificate.

        Args:
            service_id: Service identifier.
            pem: PEM certificate string.
            expires_at: Certificate expiration time.
            description: Optional description.
            uploaded_by: Optional uploader identifier.

        Returns:
            Stored CertEntry.
        """
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
        """Get certificate history for a service.

        Args:
            service_id: Service identifier.

        Returns:
            List of historical CertEntry objects.
        """
        return await self._backend.history(service_id)

    async def get_expiring_soon(self) -> list[CertEntry]:
        """Get certificates expiring within warning threshold.

        Returns:
            List of expiring CertEntry objects.
        """
        deadline = datetime.now(tz=UTC) + timedelta(
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
                if result is not None and hasattr(result, "__await__"):
                    await result
            except Exception as exc:
                logger.warning("CertStore listener failed: %s", exc)
