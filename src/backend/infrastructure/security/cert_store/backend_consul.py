"""S128 W1 — ConsulCertBackend (TD-024).

Consul KV v2 backend для CertStore. Аналог :class:`VaultCertBackend`,
но использует Consul (уже в deps для hot-reload feature flags).

Каждому ``service_id`` соответствует Consul KV path
``{base_path}/{service_id}`` с полями ``pem``, ``fingerprint``,
``expires_at`` (ISO format), ``description``, ``version``.

Consul KV v2 НЕ имеет native history (только current value), поэтому
``history()`` возвращает single-element list. Для полноценной истории
рекомендуется VaultCertBackend; Consul подходит для hot-reload
scenarios где история не критична.

Lazy import: ``consul`` package импортируется только при первом
``_client()`` вызове. Если Consul недоступен — ``get()`` возвращает
``None`` + warning, ``save()`` raises ``ConnectionError``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.backend.infrastructure.logging.factory import get_logger
from src.backend.infrastructure.security.cert_store.backend_base import CertBackend
from src.backend.infrastructure.security.cert_store.models import CertEntry

logger = get_logger("infrastructure.cert_store.consul")


@dataclass
class ConsulCertBackend(CertBackend):
    """Consul KV v2 backend (между Vault и PostgreSQL по reliability).

    Args:
        base_path: Базовый Consul KV path (default ``"certs"``).
        host: Consul host (default ``"localhost"``).
        port: Consul port (default 8500).
        token: ACL token (опционально).
    """

    name = "consul"

    def __init__(
        self,
        base_path: str = "certs",
        host: str = "localhost",
        port: int = 8500,
        token: str | None = None,
    ) -> None:
        self._base = base_path.rstrip("/")
        self._host = host
        self._port = port
        self._token = token
        self._client: Any | None = None

    def _client_factory(self) -> Callable[[], Any]:
        """Lazy client factory — Consul only loaded on first get/save."""

        def _factory() -> Any:
            if self._client is None:
                import consul

                self._client = consul.Consul(
                    host=self._host, port=self._port, token=self._token
                )
            return self._client

        return _factory

    def _kv_path(self, service_id: str) -> str:
        return f"{self._base}/{service_id}"

    async def get(self, service_id: str) -> CertEntry | None:
        try:
            client = self._client_factory()()

            def _read() -> tuple[int, Any]:
                return client.kv.get(self._kv_path(service_id))

            _, data = await asyncio.to_thread(_read)
        except Exception as exc:
            logger.warning("Consul read failed for %s: %s", service_id, exc)
            return None

        if not data or not data.get("Value"):
            return None

        try:
            payload = json.loads(data["Value"].decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("Consul cert decode failed for %s: %s", service_id, exc)
            return None

        pem = payload.get("pem", "")
        return CertEntry(
            service_id=service_id,
            pem=pem,
            fingerprint=payload.get("fingerprint") or _fingerprint(pem),
            expires_at=datetime.fromisoformat(payload["expires_at"]),
            description=payload.get("description"),
            version=int(payload.get("version", 1)),
        )

    async def save(
        self,
        service_id: str,
        pem: str,
        fingerprint: str | None,
        expires_at: datetime,
        description: str | None = None,
        uploaded_by: str | None = None,
    ) -> CertEntry:
        client = self._client_factory()()
        # Read current version to bump.
        version = 1
        try:

            def _read_existing() -> tuple[int, Any]:
                return client.kv.get(self._kv_path(service_id))

            _, existing = await asyncio.to_thread(_read_existing)
            if existing and existing.get("Value"):
                prev = json.loads(existing["Value"].decode("utf-8"))
                version = int(prev.get("version", 0)) + 1
        except Exception as exc:
            logger.debug("Consul previous-version read failed (ok): %s", exc)

        payload = {
            "pem": pem,
            "fingerprint": fingerprint or _fingerprint(pem),
            "expires_at": expires_at.isoformat(),
            "description": description or "",
            "version": version,
            "uploaded_by": uploaded_by or "",
            "updated_at": datetime.utcnow().isoformat(),
        }
        encoded = json.dumps(payload).encode("utf-8")

        def _put() -> bool:
            return client.kv.put(self._kv_path(service_id), encoded)

        try:
            await asyncio.to_thread(_put)
        except Exception as exc:
            raise ConnectionError(f"Consul put failed for {service_id}: {exc}") from exc

        return CertEntry(
            service_id=service_id,
            pem=pem,
            fingerprint=payload["fingerprint"],
            expires_at=expires_at,
            description=description,
            version=version,
        )

    async def history(self, service_id: str) -> list[CertEntry]:
        """Consul KV v2 has no native history — return current as single-item list."""
        entry = await self.get(service_id)
        return [entry] if entry else []

    async def list_expiring(self, before: datetime) -> list[CertEntry]:
        """Scan all keys under ``{base_path}/`` + filter by expires_at.

        Note: requires Consul ACL ``read`` on the prefix. Uses
        blocking scan via ``kv.get(prefix, recurse=True)``.
        """
        try:
            client = self._client_factory()()

            def _scan() -> tuple[int, list[str]]:
                return client.kv.get(self._base, recurse=True, keys=True)

            _, keys = await asyncio.to_thread(_scan)
        except Exception as exc:
            logger.warning("Consul scan failed for %s: %s", self._base, exc)
            return []

        prefix = f"{self._base}/"
        result: list[CertEntry] = []
        for key in keys or []:
            if not key.startswith(prefix):
                continue
            service_id = key[len(prefix) :]
            entry = await self.get(service_id)
            if entry and entry.expires_at <= before:
                result.append(entry)
        return result


def _fingerprint(pem: str) -> str:
    """Best-effort SHA-256 fingerprint от PEM (lazy import)."""
    import hashlib

    if not pem:
        return ""
    # Strip BEGIN/END lines + newlines for stable hash.
    body = "".join(
        line for line in pem.splitlines() if "BEGIN" not in line and "END" not in line
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
