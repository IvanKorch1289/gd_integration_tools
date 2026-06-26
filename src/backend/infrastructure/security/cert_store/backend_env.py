"""Env-inline cert backend (S171 M18, D248).

Cert store backend, читающий PEM из ENV vars ``CERT_INLINE_<cert_id>``.
Используется как terminal fallback при отсутствии vault и file.
Аналог .env для настроек (per user directive).

Безопасность: ENV vars попадают в логи/docker inspect. Используйте только
для dev/edge cases. Production: vault primary + file fallback.

NOT to be confused with .env файлами (запрещены per AGENTS.md).
"""
from __future__ import annotations

from datetime import datetime
import os

from src.backend.core.logging import get_logger
from src.backend.infrastructure.security.cert_store.backend_base import (
    CertBackend,
    CertEntry,
)
from src.backend.infrastructure.security.cert_store.models import make_cert_entry

_logger = get_logger("security.cert_store.env")

__all__ = ("EnvInlineCertBackend",)


def _cert_id_to_env(service_id: str) -> str:
    """cert_id -> CERT_INLINE_<CERT_ID>."""
    return f"CERT_INLINE_{service_id.upper().replace('-', '_').replace('.', '_')}"


class EnvInlineCertBackend(CertBackend):
    """Backend чтения PEM из ENV vars ``CERT_INLINE_<cert_id>``.

    Пример:
        export CERT_INLINE_SKB_API='---BEGIN CERT---\n...\n---END CERT---'
    """

    async def get(self, service_id: str) -> CertEntry | None:
        env_name = _cert_id_to_env(service_id)
        pem = os.environ.get(env_name)
        if not pem:
            return None
        return make_cert_entry(service_id=service_id, pem=pem)

    async def set(self, service_id: str, pem: str) -> None:
        _logger.warning(
            "cert.env.set_noop id=%s (ENV vars read-only at runtime; "
            "use vault or file backend for persistence)",
            service_id,
        )

    async def delete(self, service_id: str) -> bool:
        _logger.warning("cert.env.delete_noop id=%s", service_id)
        return False


    async def save(self, service_id: str, pem: str, expires_at: datetime | None = None) -> None:
        """ENV — read-only, delegate to set (which is noop)."""
        await self.set(service_id, pem)

    async def history(self, service_id: str) -> list[CertEntry]:
        """ENV — no history."""
        current = await self.get(service_id)
        return [current] if current else []

    async def list_expiring(self, before: datetime) -> list[CertEntry]:
        return []


    def list_all(self) -> list[str]:
        return sorted(
            k.removeprefix("CERT_INLINE_").lower()
            for k in os.environ
            if k.startswith("CERT_INLINE_")
        )
