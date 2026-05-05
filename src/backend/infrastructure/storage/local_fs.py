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

import aiofiles
import aiofiles.os

from src.core.interfaces.storage import ObjectStorage

__all__ = ("LocalFSStorage",)


class LocalFSStorage(ObjectStorage):
    """LocalFS-реализация ``ObjectStorage`` для dev-окружения."""

    def __init__(self, base_path: str | os.PathLike[str]) -> None:
        self._base = Path(base_path).expanduser().resolve()
        self._base.mkdir(parents=True, exist_ok=True)

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
        path = self._safe_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        async with aiofiles.open(tmp, "wb") as fh:
            await fh.write(data)
        await aiofiles.os.replace(str(tmp), str(path))
        return str(path)

    async def download(self, key: str) -> bytes:
        path = self._safe_path(key)
        async with aiofiles.open(path, "rb") as fh:
            return await fh.read()

    async def delete(self, key: str) -> None:
        path = self._safe_path(key)
        try:
            await aiofiles.os.remove(str(path))
        except FileNotFoundError:
            pass

    async def exists(self, key: str) -> bool:
        path = self._safe_path(key)
        return await aiofiles.os.path.exists(str(path))

    async def list_keys(self, prefix: str = "") -> list[str]:
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
        path = self._safe_path(key)
        return path.as_uri()
