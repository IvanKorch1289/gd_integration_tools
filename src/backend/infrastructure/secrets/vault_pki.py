"""Vault PKI client — Sprint 12 K1 W2.

Lazy-import обёртка над ``hvac.Client`` для issue/renew TLS-сертификатов
через Vault PKI engine. Используется :class:`TemporalClientFactory` для
production-mTLS workers с автоматическим cert rotation.

Контракт:

* :meth:`issue_cert(role, common_name, ttl)` — возвращает
  :class:`CertificateBundle` с PEM cert/key/ca.
* Cache по ``(role, common_name)`` с проверкой ``not_after``;
  при истечении < buffer (по умолчанию 1h) — renew.
* Read-only: никаких revocation/rotation operations (для них
  отдельный rotator).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

__all__ = ("CertificateBundle", "VaultPkiClient")

_logger = logging.getLogger("infrastructure.secrets.vault_pki")


@dataclass(frozen=True, slots=True)
class CertificateBundle:
    """PEM-bundle от Vault PKI engine."""

    certificate: str
    private_key: str
    ca_chain: str
    not_after: datetime
    serial_number: str


@dataclass(slots=True)
class _CachedCert:
    bundle: CertificateBundle
    cached_at: float


class VaultPkiClient:
    """Lazy-init wrapper для Vault PKI ``pki/issue/<role>``.

    Args:
        vault_addr: ``http://vault:8200`` (если ``None`` — из env).
        vault_token: токен (если ``None`` — из env ``VAULT_TOKEN``).
        pki_mount: путь к PKI engine (default ``pki``).
        renew_buffer_seconds: renew за N секунд до not_after (default 3600).
    """

    def __init__(
        self,
        *,
        vault_addr: str | None = None,
        vault_token: str | None = None,
        pki_mount: str = "pki",
        renew_buffer_seconds: int = 3600,
    ) -> None:
        self._addr = vault_addr
        self._token = vault_token
        self._mount = pki_mount
        self._renew_buffer = renew_buffer_seconds
        self._client: Any = None
        self._cache: dict[tuple[str, str], _CachedCert] = {}
        self._lock = threading.Lock()

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        with self._lock:
            if self._client is not None:
                return self._client
            import os

            import hvac

            addr = self._addr or os.environ.get("VAULT_ADDR", "http://127.0.0.1:8200")
            token = self._token or os.environ.get("VAULT_TOKEN")
            self._client = hvac.Client(url=addr, token=token)
            return self._client

    def issue_cert(
        self, *, role: str, common_name: str, ttl: str = "24h"
    ) -> CertificateBundle:
        """Issue TLS cert через PKI engine.

        Cache: для (role, common_name) возвращает предыдущий bundle,
        если ``not_after - now > renew_buffer``. Иначе issue новый.
        """
        key = (role, common_name)
        now = datetime.now(UTC)
        cached = self._cache.get(key)
        if cached is not None:
            time_to_expire = (cached.bundle.not_after - now).total_seconds()
            if time_to_expire > self._renew_buffer:
                return cached.bundle

        client = self._get_client()
        path = f"{self._mount}/issue/{role}"
        response = client.write_data(
            path=path, data={"common_name": common_name, "ttl": ttl}
        )
        if not response:
            raise RuntimeError(f"Vault PKI issue empty response для {path}")
        data = response.get("data") if isinstance(response, dict) else response
        if data is None or not isinstance(data, dict):
            raise RuntimeError(f"Vault PKI issue missing data для {path}")

        not_after = self._parse_expiration(data, ttl=ttl)
        bundle = CertificateBundle(
            certificate=data["certificate"],
            private_key=data["private_key"],
            ca_chain="\n".join(data.get("ca_chain", [data.get("issuing_ca", "")])),
            not_after=not_after,
            serial_number=data.get("serial_number", ""),
        )

        with self._lock:
            self._cache[key] = _CachedCert(bundle=bundle, cached_at=time.time())

        _logger.info(
            "Vault PKI issued cert: role=%s cn=%s ttl=%s serial=%s",
            role,
            common_name,
            ttl,
            bundle.serial_number,
        )
        return bundle

    def invalidate(self, *, role: str, common_name: str) -> None:
        """Сбросить cache для (role, common_name) — для ручного rotation."""
        with self._lock:
            self._cache.pop((role, common_name), None)

    @staticmethod
    def _parse_expiration(data: dict[str, Any], *, ttl: str) -> datetime:
        """Парсит ``expiration`` (Unix timestamp) или вычисляет из ttl."""
        exp = data.get("expiration")
        if isinstance(exp, (int, float)):
            return datetime.fromtimestamp(exp, tz=UTC)
        seconds = _parse_ttl_to_seconds(ttl)
        return datetime.now(UTC) + timedelta(seconds=seconds)


def _parse_ttl_to_seconds(ttl: str) -> int:
    """``"24h"`` / ``"30m"`` / ``"3600"`` → seconds."""
    if not ttl:
        return 0
    suffix = ttl[-1].lower()
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if suffix in multipliers:
        try:
            return int(ttl[:-1]) * multipliers[suffix]
        except ValueError:
            return 86400
    try:
        return int(ttl)
    except ValueError:
        return 86400
