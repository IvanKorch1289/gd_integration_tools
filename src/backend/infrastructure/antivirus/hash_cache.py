"""Кэш AV-вердиктов по SHA-256 хэшу payload-а (Wave 2.4).

Хранилище — Redis, ключ ``antivirus:hash:<sha256>``. TTL по умолчанию
1 час: повторное сканирование того же файла (ровно тот же байтовый
поток) возвращает кэшированный вердикт без обращения в ClamAV/HTTP.

Hash-кэш безопасен потому, что любой даже малейший байтовый сдвиг
изменяет SHA-256 — false-positive невозможен.
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING

import orjson

from src.core.interfaces.antivirus import AntivirusScanResult

if TYPE_CHECKING:
    from redis.asyncio import Redis

__all__ = ("AntivirusHashCache",)

logger = logging.getLogger("infrastructure.antivirus.hash_cache")

_PREFIX = "antivirus:hash:"


class AntivirusHashCache:
    """SHA-256 кэш AV-вердиктов поверх Redis."""

    def __init__(self, client: Redis, default_ttl: int = 3600) -> None:
        self._client = client
        self._ttl = default_ttl

    @staticmethod
    def _key(payload: bytes) -> str:
        return _PREFIX + hashlib.sha256(payload).hexdigest()

    async def get(self, payload: bytes) -> AntivirusScanResult | None:
        try:
            raw = await self._client.get(self._key(payload))
        except Exception as exc:  # noqa: BLE001
            logger.debug("hash_cache: get failed %s", exc)
            return None
        if not raw:
            return None
        try:
            data = orjson.loads(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("hash_cache: corrupt entry %s", exc)
            return None
        return AntivirusScanResult(
            clean=bool(data.get("clean")),
            signature=data.get("signature"),
            backend="cache",
            latency_ms=0.0,
        )

    async def put(
        self, payload: bytes, result: AntivirusScanResult, ttl: int | None = None
    ) -> None:
        try:
            await self._client.set(
                self._key(payload),
                orjson.dumps({"clean": result.clean, "signature": result.signature}),
                ex=ttl or self._ttl,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("hash_cache: put failed %s", exc)
