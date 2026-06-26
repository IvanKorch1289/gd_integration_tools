"""File-based cert backend (S171 M18, D248).

Cert store backend, читающий .pem/.crt файлы из директории.
Используется как fallback при недоступности Vault (per user directive:
"для настроек есть .env, а для сертификатов ничего нет").

Pattern (D248, D247): lazy file I/O, no caching (CertStore имеет hot cache).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.backend.core.logging import get_logger
from src.backend.infrastructure.security.cert_store.backend_base import (
    CertBackend,
    CertEntry,
)
from src.backend.infrastructure.security.cert_store.models import make_cert_entry

_logger = get_logger("security.cert_store.file")

__all__ = ("FileCertBackend",)


class FileCertBackend(CertBackend):
    """Backend чтения/записи .pem файлов из локальной директории.

    Args:
        path: Директория с .pem/.crt файлами (cert_id = filename без расширения).
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.mkdir(parents=True, exist_ok=True)

    def _resolve_path(self, service_id: str) -> Path | None:
        """Найти файл с .pem или .crt расширением."""
        for ext in (".pem", ".crt"):
            candidate = self.path / f"{service_id}{ext}"
            if candidate.exists():
                return candidate
        return None

    async def get(self, service_id: str) -> CertEntry | None:
        path = self._resolve_path(service_id)
        if path is None:
            return None
        try:
            pem = path.read_text(encoding="utf-8")
            return make_cert_entry(service_id=service_id, pem=pem)
        except OSError as exc:
            _logger.warning("cert.file.read_error id=%s: %s", service_id, exc)
            return None

    async def set(self, service_id: str, pem: str) -> None:
        path = self.path / f"{service_id}.pem"
        path.write_text(pem, encoding="utf-8")
        try:
            path.chmod(0o600)  # owner-only
        except OSError:
            pass
        _logger.info("cert.file.set id=%s path=%s", service_id, path)

    async def delete(self, service_id: str) -> bool:
        path = self._resolve_path(service_id)
        if path is None:
            return False
        path.unlink()
        return True


    async def save(self, service_id: str, pem: str, expires_at: datetime | None = None) -> None:
        """Alias для set (CertBackend ABC signature)."""
        await self.set(service_id, pem)

    async def history(self, service_id: str) -> list[CertEntry]:
        """История: для file backend — только текущая запись."""
        current = await self.get(service_id)
        return [current] if current else []

    async def list_expiring(self, before: datetime) -> list[CertEntry]:
        """File backend не хранит expires_at — возвращает пусто."""
        return []


    def list_all(self) -> list[str]:
        """Список cert_id в директории (для admin/debug)."""
        names: set[str] = set()
        for ext in (".pem", ".crt"):
            for p in self.path.glob(f"*{ext}"):
                names.add(p.stem)
        return sorted(names)
