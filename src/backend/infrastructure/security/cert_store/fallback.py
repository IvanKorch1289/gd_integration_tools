"""Fallback cert backend (S171 M18, D248).

Цепочка fallback: primary → secondary → terminal.
Используется в production: vault primary, file secondary, env_inline terminal.

Per user directive: "продумай fallback логику для SSL Cert, если
Hashicorp Vault недоступен".
"""
from __future__ import annotations

from datetime import datetime

from src.backend.core.logging import get_logger
from src.backend.infrastructure.security.cert_store.backend_base import (
    CertBackend,
    CertEntry,
)

_logger = get_logger("security.cert_store.fallback")

__all__ = ("FallbackCertBackend",)


class FallbackCertBackend(CertBackend):
    """Cert backend с fallback chain.

    При ``get()`` пробует primary, secondary, tertiary по очереди.
    Возвращает первое найденное значение.

    Args:
        primary: Primary backend (например VaultCertBackend).
        secondary: Fallback backend (например FileCertBackend).
        tertiary: Terminal fallback (например EnvInlineCertBackend). Optional.
    """

    def __init__(
        self,
        *,
        primary: CertBackend,
        secondary: CertBackend,
        tertiary: CertBackend | None = None,
    ) -> None:
        self._primary = primary
        self._secondary = secondary
        self._tertiary = tertiary
        self._chain = [("primary", primary), ("secondary", secondary), ("tertiary", tertiary)]

    async def save(self, service_id: str, pem: str, expires_at: datetime | None = None) -> None:
        """Save через primary."""
        from datetime import datetime
        await self._primary.save(service_id, pem, expires_at)

    async def history(self, service_id: str) -> list[CertEntry]:
        from src.backend.infrastructure.security.cert_store.backend_base import CertEntry
        return []

    async def list_expiring(self, before: datetime) -> list[CertEntry]:
        from src.backend.infrastructure.security.cert_store.backend_base import CertEntry
        return []


        self._chain = [
            ("primary", primary),
            ("secondary", secondary),
            ("tertiary", tertiary),
        ]

    async def get(self, service_id: str) -> CertEntry | None:
        for name, backend in self._chain:
            if backend is None:
                continue
            try:
                entry = await backend.get(service_id)
                if entry is not None:
                    if name != "primary":
                        _logger.info(
                            "cert.fallback.hit chain=%s id=%s",
                            name, service_id,
                        )
                    return entry
            except Exception as exc:
                _logger.warning(
                    "cert.fallback.error chain=%s id=%s: %s",
                    name, service_id, exc,
                )
                continue
        return None

    async def set(self, service_id: str, pem: str) -> None:
        """Set делегируется в primary (vault — canonical)."""
        await self._primary.set(service_id, pem)

    async def delete(self, service_id: str) -> bool:
        """Delete пробует все backends."""
        results = []
        for _, backend in self._chain:
            if backend is None:
                continue
            try:
                results.append(await backend.delete(service_id))
            except Exception:
                pass
        return any(results)
