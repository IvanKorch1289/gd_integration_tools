"""Disk-backed cache для decorators-caching — **без pickle** (PYSEC-2026-2447).

Ранее использовался diskcache.Cache (последняя версия 5.6.3 уязвима целиком,
upstream-фикса нет — зависимости удалены). Значения хранятся как bytes-файлы
с sha256-шардированием, индекс ключей — один JSON-файл (нужен для
``delete_pattern``).

Ограничение (ponytail): индекс in-memory per-process, атомарно
перезаписывается на диск при мутациях. Multi-process шаринг не поддерживается
(у diskcache был через sqlite); путь апгрейда — redis-бэкенд либо sqlite.
TTL живёт на уровне envelope (``is_alive``/``pop`` при протухании), файлы
протухших записей удаляются при следующем обращении по тому же ключу.
"""

from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from src.backend.core.codec.json import json_dumps, json_loads
from src.backend.infrastructure.decorators.caching.envelope import CacheEnvelope

__all__ = ("DiskTTLCache",)


class _IndexedByteStore:
    """Byte-store: значения — файлы, ключи — JSON-индекс (pickle-free)."""

    def __init__(self, directory: Path) -> None:
        self._base = directory
        # PYSEC-2026-2447: отсекаем запись третьими сторонами (при создании).
        self._base.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._index_path = self._base / "index.json"
        self._index: dict[str, str] = self._load_index()

    @staticmethod
    def _path_for(base: Path, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return base / digest[:2] / digest

    def _load_index(self) -> dict[str, str]:
        try:
            raw = self._index_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_index(self) -> None:
        fd, tmp_name = tempfile.mkstemp(dir=self._base, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._index, f)
            os.replace(tmp_name, self._index_path)
        except OSError:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def get(self, key: str) -> bytes | None:
        path = self._path_for(self._base, key)
        try:
            return path.read_bytes()
        except OSError:
            return None

    def set(self, key: str, data: bytes) -> None:
        path = self._path_for(self._base, key)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_bytes(data)
        self._index[key] = str(path.relative_to(self._base))
        self._save_index()

    def pop(self, key: str) -> bytes | None:
        data = self.get(key)
        self.delete(key)
        return data

    def delete(self, key: str) -> None:
        if self._index.pop(key, None) is not None:
            self._save_index()
        try:
            self._path_for(self._base, key).unlink()
        except OSError:
            pass

    def keys(self) -> list[str]:
        return list(self._index)

    def close(self) -> None:
        self._save_index()


class DiskTTLCache:
    """Disk-backed cache с envelope-семантикой (TTL/stale — на envelope)."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self._store = _IndexedByteStore(self.directory)

    @staticmethod
    def _serialize_envelope(envelope: CacheEnvelope) -> bytes:
        raw = json_dumps(envelope.to_dict())
        return raw if isinstance(raw, bytes) else raw.encode("utf-8")

    @staticmethod
    def _deserialize_envelope(raw: bytes) -> CacheEnvelope | None:
        try:
            payload = json_loads(raw)
            return CacheEnvelope.from_payload(payload)
        except Exception as _:  # noqa: BLE001 — битая запись = cache miss
            return None

    def _get_sync(self, key: str) -> CacheEnvelope | None:
        raw = self._store.get(key)
        if raw is None:
            return None

        envelope = self._deserialize_envelope(raw)
        if envelope is None:
            self._store.delete(key)
            return None

        if not envelope.is_alive():
            self._store.pop(key)
            return None

        return envelope

    def _set_sync(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None,
        stale_if_error_seconds: int = 0,
    ) -> None:
        envelope = CacheEnvelope.create(
            value=value,
            ttl_seconds=ttl_seconds,
            stale_if_error_seconds=stale_if_error_seconds,
        )
        self._store.set(key, self._serialize_envelope(envelope))

    def _delete_sync(self, *keys: str) -> None:
        for key in keys:
            self._store.delete(key)

    def _delete_pattern_sync(self, pattern: str) -> None:
        matched = [
            key for key in self._store.keys() if fnmatch.fnmatch(key, pattern)
        ]
        for key in matched:
            self._store.delete(key)

    def _close_sync(self) -> None:
        self._store.close()

    async def get(self, key: str, renew_ttl: bool = False) -> CacheEnvelope | None:
        """Получить cache entry; опц. обновить TTL при чтении (``renew_ttl=True``)."""
        envelope = await asyncio.to_thread(self._get_sync, key)

        if (
            envelope is not None
            and renew_ttl
            and envelope.is_fresh()
            and envelope.ttl_seconds
        ):
            envelope = await asyncio.to_thread(
                self._set_renewed_sync, key, envelope
            )

        return envelope

    def _set_renewed_sync(self, key: str, envelope: CacheEnvelope) -> CacheEnvelope:
        renewed = envelope.renew()
        self._store.set(key, self._serialize_envelope(renewed))
        return renewed

    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None,
        stale_if_error_seconds: int = 0,
    ) -> None:
        """Сохранить ``value`` с TTL + опц. stale_if_error."""
        await asyncio.to_thread(
            self._set_sync, key, value, ttl_seconds, stale_if_error_seconds
        )

    async def delete(self, *keys: str) -> None:
        """Удалить один или несколько ключей."""
        await asyncio.to_thread(self._delete_sync, *keys)

    async def delete_pattern(self, pattern: str) -> None:
        """Удалить все ключи matching pattern (Redis SCAN-style)."""
        await asyncio.to_thread(self._delete_pattern_sync, pattern)

    async def close(self) -> None:
        """Закрыть cache backend (graceful shutdown)."""
        await asyncio.to_thread(self._close_sync)
