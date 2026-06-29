"""S55 W1 — backend_vault.py part of cert_store decomp.

Classes: VaultCertBackend.
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
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.infrastructure.security.cert_store.models import (
    CertEntry,
    _fingerprint,
)

logger = get_logger("infrastructure.cert_store")


@dataclass
class VaultCertBackend(CertBackend):
    """HashiCorp Vault KV v2 бэкенд (prod-рекомендация).

    Каждому ``service_id`` соответствует путь ``{base_path}/{service_id}``
    с полями ``pem``, ``fingerprint``, ``expires_at``, ``description``,
    ``version``. История ведётся на стороне Vault (KV v2 хранит revisions).
    """

    name = "vault"

    def __init__(
        self,
        base_path: str,
        *,
        vault_url: str | None = None,
        token: str | None = None,
        role_id: str | None = None,
        secret_id: str | None = None,
        kubernetes_role: str | None = None,
    ) -> None:
        """VaultCertBackend с поддержкой 3 auth methods (D255).

        Args:
            base_path: Базовый путь в Vault KV v2.
            vault_url: Vault URL (если None — из settings).
            token: Static token (fallback auth, D255 backward compat).
            role_id: AppRole role_id (D255 NEW, preferred для prod).
            secret_id: AppRole secret_id (D255 NEW).
            kubernetes_role: K8s auth role (D255 NEW, для Vault Agent sidecar).

        Приоритет: kubernetes_role > role_id/secret_id > token.
        """
        self._base = base_path.rstrip("/")
        self._vault_url = vault_url
        self._token = token
        self._role_id = role_id
        self._secret_id = secret_id
        self._kubernetes_role = kubernetes_role
        self._client: Any = None  # lazy init

    def _resolve_url(self) -> str | None:
        """Получить vault_url: kwarg → settings."""
        if self._vault_url:
            return self._vault_url
        from src.backend.core.config.settings import settings
        return getattr(settings, "vault_url", None) or getattr(
            settings.app, "vault_url", None
        )

    def _authenticate(self, client: Any) -> None:
        """AppRole/K8s/static token auth (D255).

        Приоритет:
        1. kubernetes_role (Vault Agent sidecar, JWT in pod)
        2. role_id + secret_id (AppRole, rotating secrets)
        3. static token (legacy, dev)
        """
        if self._kubernetes_role:
            client.auth.kubernetes.login(role=self._kubernetes_role)
            return
        if self._role_id and self._secret_id:
            resp = client.auth.approle.login(
                role_id=self._role_id, secret_id=self._secret_id
            )
            return
        if self._token:
            client.token = self._token
            return
        raise ConnectionError("Vault: no auth method configured")

    def _client(self) -> Any:
        """Lazy hvac.Client + auth (D255)."""
        if self._client is not None:
            return self._client
        from hvac import Client  # лениво, чтобы тесты без Vault работали
        url = self._resolve_url()
        client = Client(url=url)
        self._authenticate(client)
        if not client.is_authenticated():
            raise ConnectionError("Vault: не аутентифицирован")
        self._client = client
        return client

    async def get(self, service_id: str) -> CertEntry | None:
        """Get certificate from Vault.

        Args:
            service_id: Service identifier.

        Returns:
            CertEntry or None if not found.
        """
        try:
            client = self._client()
            data = await asyncio.to_thread(
                client.secrets.kv.v2.read_secret_version,
                path=f"{self._base}/{service_id}",
            )
        except Exception as exc:
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
        """Save certificate to Vault.

        Args:
            service_id: Service identifier.
            pem: PEM certificate string.
            expires_at: Certificate expiration time.
            description: Optional description.
            uploaded_by: Optional uploader identifier.

        Returns:
            Saved CertEntry with incremented version.
        """
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
        client = self._client()
        await asyncio.to_thread(
            client.secrets.kv.v2.create_or_update_secret,
            path=f"{self._base}/{service_id}",
            secret=secret,
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
