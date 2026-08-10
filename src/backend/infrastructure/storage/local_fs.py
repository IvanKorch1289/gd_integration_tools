"""LocalFS бэкенд объектного хранилища для dev-стенда (Wave 2.3).

Реализует :class:`core.interfaces.ObjectStorage` поверх локальной
директории. Активируется при ``FS_PROVIDER=local``.

В **production** не использовать — нет шифрования, репликации, CDN.
При запуске вне dev-окружения выводит ``warnings.warn``, чтобы предупредить
оператора о небезопасной конфигурации.

Особенности:

* ``upload`` пишет файл атомарно (через временный файл + rename);
* ``presigned_url`` отдаёт ``file://...`` URL — действующая ссылка только
  локально, годится для smoke-тестов и dev-фронтенда;
* ``list_keys`` обходит дерево рекурсивно (``rglob``);
* безопасность путей — отсев ``..``, абсолютные ключи отклоняются.
"""

from __future__ import annotations

import asyncio
import os
import warnings
from pathlib import Path
from typing import Any

import aiofiles
import aiofiles.os

from src.backend.core.interfaces.storage import ObjectStorage
from src.backend.infrastructure.clients.base_connector import HealthResult


def _is_safe_tenant_segment(tenant_id: str) -> bool:
    """Cycle-16 (D-AUDIT-1601): slug regex для tenant_id в FS-layout.

    Разрешены alphanumeric + underscore + dash, max 64 chars. Не
    разрешены: ``..`` (path traversal), ``/`` (path separator),
    точки/спецсимволы, non-ASCII.
    """
    import re as _re

    return bool(_re.match(r"^[a-zA-Z0-9_-]{1,64}$", tenant_id))

__all__ = ("LocalFSStorage",)


class LocalFSStorage(ObjectStorage):
    """LocalFS-реализация ``ObjectStorage`` для dev-окружения.

    Cycle-16 (D-AUDIT-1601): добавлен :meth:`tenant_root` — multi-tenant
    safe-path layout. Используется в app_factory для auto-prefixing
    ключей (``<tenant_id>/<key>``) — это позволяет LocalFS-режиму
    изолировать файлы по tenant'ам без изменения ObjectStorage.Protocol.
    """

    def __init__(
        self,
        base_path: str | os.PathLike[str],
        *,
        tenant_root_prefix: str = "tenants",
    ) -> None:
        self._base = Path(base_path).expanduser().resolve()
        self._base.mkdir(parents=True, exist_ok=True)
        self._tenant_root_prefix = tenant_root_prefix

        env = os.environ.get("APP_ENVIRONMENT") or os.environ.get(
            "ENVIRONMENT", "development"
        )
        if env.lower() in {"prod", "production"}:
            warnings.warn(
                "LocalFSStorage активирован в production — это небезопасно. "
                "Используйте S3/MinIO/AWS вместо provider=local.",
                RuntimeWarning,
                stacklevel=2,
            )

    def tenant_root(self, tenant_id: str | None) -> Path:
        """Возвращает корень tenant'а в local FS.

        Multi-tenant layout: ``<base>/<tenant_root_prefix>/<tenant_id>/``.
        System uploads (tenant_id=None): ``<base>/<tenant_root_prefix>/_system/``.

        Args:
            tenant_id: Tenant identifier (None для system uploads).

        Returns:
            Path к корню tenant'а (создаётся при первом обращении).
        """
        # Cycle-16 (D-AUDIT-1601): slug validation через shared helper.
        if tenant_id is not None and not _is_safe_tenant_segment(tenant_id):
            raise ValueError(f"Небезопасный tenant_id для LocalFSStorage: {tenant_id!r}")
        slug = tenant_id if tenant_id is not None else "_system"
        return self._base / self._tenant_root_prefix / slug


    def _safe_path(self, key: str) -> Path:
        """Резолвит ``key`` относительно base_path, отсекая path-traversal."""
        if not key or key.startswith("/") or ".." in key.split("/"):
            raise ValueError(f"Небезопасный ключ объекта: {key!r}")
        path = (self._base / key).resolve()
        if not str(path).startswith(str(self._base)):
            raise ValueError(f"Ключ выходит за пределы base_path: {key!r}")
        return path

    async def upload(
        self, key: str, data: bytes, content_type: str | None = None
    ) -> str:
        """Upload data to local filesystem.

        Args:
            key: Object key (relative path).
            data: Binary data to upload.
            content_type: MIME type (unused for local FS).

        Returns:
            Absolute path to uploaded file.
        """
        path = self._safe_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        async with aiofiles.open(tmp, "wb") as fh:
            await fh.write(data)
        await aiofiles.os.replace(str(tmp), str(path))
        return str(path)

    async def download(self, key: str) -> bytes:
        """Download data from local filesystem.

        Args:
            key: Object key (relative path).

        Returns:
            File contents as bytes.
        """
        path = self._safe_path(key)
        async with aiofiles.open(path, "rb") as fh:
            return await fh.read()

    async def delete(self, key: str) -> None:
        """Delete object from local filesystem.

        Args:
            key: Object key (relative path).
        """
        path = self._safe_path(key)
        try:
            await aiofiles.os.remove(str(path))
        except FileNotFoundError:
            pass

    async def exists(self, key: str) -> bool:
        """Check if object exists in local filesystem.

        Args:
            key: Object key (relative path).

        Returns:
            True if object exists, False otherwise.
        """
        path = self._safe_path(key)
        return await aiofiles.os.path.exists(str(path))

    async def list_keys(self, prefix: str = "") -> list[str]:
        """List all object keys with given prefix.

        Args:
            prefix: Key prefix to filter by.

        Returns:
            Sorted list of matching keys.
        """
        return await asyncio.to_thread(self._list_sync, prefix)

    def _list_sync(self, prefix: str) -> list[str]:
        root = self._safe_path(prefix) if prefix else self._base
        if not root.exists():
            return []
        if root.is_file():
            return [str(root.relative_to(self._base).as_posix())]
        result: list[str] = []
        for path in root.rglob("*"):
            if path.is_file() and not path.name.endswith(".tmp"):
                result.append(str(path.relative_to(self._base).as_posix()))
        return sorted(result)

    async def presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """Get presigned URL for object (returns file:// URI for local FS).

        Args:
            key: Object key (relative path).
            expires_in: Expiration time in seconds (unused for local FS).

        Returns:
            File URI string.
        """
        path = self._safe_path(key)
        return path.as_uri()

    async def upload_stream(
        self,
        key: str,
        stream: Any,
        content_type: str | None = None,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Потоковая запись чанков в локальный файл (atomic via tmp + rename)."""
        from collections.abc import AsyncIterable

        path = self._safe_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        async with aiofiles.open(tmp, "wb") as fh:
            if isinstance(stream, AsyncIterable):
                async for chunk in stream:
                    await fh.write(chunk)
            else:
                # Поддержка sync-итератора через to_thread (avoid blocking).
                for chunk in stream:
                    await asyncio.to_thread(fh.write, chunk)
        await aiofiles.os.replace(str(tmp), str(path))
        return str(path)

    async def health(self, mode: str = "fast") -> HealthResult:
        """Проверяет доступность base_path (readable + writable)."""
        import time

        start = time.perf_counter()
        try:
            if not self._base.exists():
                latency_ms = (time.perf_counter() - start) * 1000.0
                return HealthResult.failed(
                    error="base_path does not exist", mode=mode, latency_ms=latency_ms
                )
            if not os.access(str(self._base), os.R_OK | os.W_OK):
                latency_ms = (time.perf_counter() - start) * 1000.0
                return HealthResult.failed(
                    error="base_path not readable/writable",
                    mode=mode,
                    latency_ms=latency_ms,
                )
            latency_ms = (time.perf_counter() - start) * 1000.0
            return HealthResult.ok(latency_ms=latency_ms, mode=mode)
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000.0
            return HealthResult.failed(
                error=f"{type(exc).__name__}: {exc}", mode=mode, latency_ms=latency_ms
            )
