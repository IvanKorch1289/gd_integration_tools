import asyncio
import fnmatch
from pathlib import Path
from typing import Any

from diskcache import Cache

from src.backend.infrastructure.decorators.caching.envelope import CacheEnvelope
from src.backend.utilities.codecs.json import json_dumps, json_loads

__all__ = ("DiskTTLCache",)


class DiskTTLCache:
    """Disk-backed cache на основе diskcache с envelope-семантикой."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._cache = Cache(str(self.directory))

    @staticmethod
    def _storage_expire(
        ttl_seconds: int | None, stale_if_error_seconds: int
    ) -> int | None:
        if ttl_seconds is None or ttl_seconds <= 0:
            return None
        return ttl_seconds + max(0, stale_if_error_seconds)

    @staticmethod
    def _serialize_envelope(envelope: CacheEnvelope) -> bytes:
        return json_dumps(envelope.to_dict())

    @staticmethod
    def _deserialize_envelope(raw: bytes) -> CacheEnvelope | None:
        try:
            payload = json_loads(raw)
            return CacheEnvelope.from_payload(payload)
        except Exception:
            return None

    def _get_sync(self, key: str) -> CacheEnvelope | None:
        raw = self._cache.get(key, default=None)
        if raw is None:
            return None

        if isinstance(raw, (bytearray, memoryview)):
            raw = bytes(raw)

        if not isinstance(raw, bytes):
            return None

        envelope = self._deserialize_envelope(raw)
        if envelope is None:
            return None

        if not envelope.is_alive():
            self._cache.pop(key, default=None)
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

        self._cache.set(
            key,
            self._serialize_envelope(envelope),
            expire=self._storage_expire(ttl_seconds, stale_if_error_seconds),
        )

    def _renew_sync(self, key: str, envelope: CacheEnvelope) -> CacheEnvelope:
        renewed = envelope.renew()
        self._cache.set(
            key,
            self._serialize_envelope(renewed),
            expire=self._storage_expire(
                renewed.ttl_seconds, renewed.stale_if_error_seconds
            ),
        )
        return renewed

    def _delete_sync(self, *keys: str) -> None:
        for key in keys:
            self._cache.pop(key, default=None)

    def _delete_pattern_sync(self, pattern: str) -> None:
        keys_to_delete = [
            key
            for key in self._cache.iterkeys()
            if isinstance(key, str) and fnmatch.fnmatch(key, pattern)
        ]
        for key in keys_to_delete:
            self._cache.pop(key, default=None)

    def _close_sync(self) -> None:
        self._cache.close()

    async def get(self, key: str, renew_ttl: bool = False) -> CacheEnvelope | None:
        envelope = await asyncio.to_thread(self._get_sync, key)

        if (
            envelope is not None
            and renew_ttl
            and envelope.is_fresh()
            and envelope.ttl_seconds
        ):
            envelope = await asyncio.to_thread(self._renew_sync, key, envelope)

        return envelope

    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None,
        stale_if_error_seconds: int = 0,
    ) -> None:
        await asyncio.to_thread(
            self._set_sync, key, value, ttl_seconds, stale_if_error_seconds
        )

    async def delete(self, *keys: str) -> None:
        await asyncio.to_thread(self._delete_sync, *keys)

    async def delete_pattern(self, pattern: str) -> None:
        await asyncio.to_thread(self._delete_pattern_sync, pattern)

    async def close(self) -> None:
        await asyncio.to_thread(self._close_sync)
