"""Unit-тесты ``AntivirusHashCache``.

Покрывает:

* miss -> ``get`` возвращает ``None`` (Redis не знает ключа);
* hit-clean -> ``put`` сохраняет clean-вердикт, ``get`` возвращает
  ``AntivirusScanResult(clean=True, backend='cache')``;
* hit-threat -> ``put`` сохраняет threat-вердикт с сигнатурой,
  ``get`` отдаёт её;
* кастомный ``ttl`` пробрасывается в ``Redis.set(ex=ttl)``;
* поломка backend'а (``get``/``set`` raise) не ломает поток —
  кэш ведёт себя как best-effort слой;
* corrupt entry в Redis -> ``get`` возвращает ``None`` (graceful degrade);
* сохранение однозначно по SHA-256: разные payload -> разные ключи.

Backend выбирается так:
* если установлен ``fakeredis`` -> используем ``FakeRedis(decode_responses=False)``;
* иначе fallback на ``unittest.mock.AsyncMock``.
"""

# ruff: noqa: S101  # assert — стандартная идиома pytest

from __future__ import annotations

import hashlib
from typing import Any
from unittest.mock import AsyncMock

import orjson
import pytest

from src.core.interfaces.antivirus import AntivirusScanResult
from src.infrastructure.antivirus.hash_cache import AntivirusHashCache

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def fake_redis() -> Any:
    """In-memory Redis-совместимый клиент.

    Если ``fakeredis`` установлен — используется реальный fake.
    Иначе — простейшая реализация на ``dict`` с поддержкой ``get``/``set``.
    """
    try:
        import fakeredis.aioredis as far

        return far.FakeRedis()
    except ImportError:
        return _DictRedis()


class _DictRedis:
    """Минимальный fake Redis с ``get``/``set`` и записью TTL."""

    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}
        self.set_calls: list[tuple[str, bytes, int | None]] = []

    async def get(self, key: str) -> bytes | None:
        return self._data.get(key)

    async def set(
        self,
        key: str,
        value: bytes,
        *,
        ex: int | None = None,
        **_: Any,
    ) -> bool:
        self._data[key] = value
        self.set_calls.append((key, value, ex))
        return True


# ── Базовые сценарии ───────────────────────────────────────────────────────


async def test_get_miss_returns_none(fake_redis: Any) -> None:
    """Если Redis не знает ключа — ``get`` возвращает ``None``."""
    cache = AntivirusHashCache(fake_redis)
    assert await cache.get(b"unseen-payload") is None


async def test_put_then_get_clean_verdict(fake_redis: Any) -> None:
    """После ``put(clean=True)`` следующий ``get`` отдаёт clean-вердикт."""
    cache = AntivirusHashCache(fake_redis)
    payload = b"clean-bytes"
    verdict = AntivirusScanResult(clean=True, backend="clamav_unix", latency_ms=5.0)

    await cache.put(payload, verdict)

    cached = await cache.get(payload)
    assert cached is not None
    assert cached.clean is True
    assert cached.signature is None
    assert cached.backend == "cache"
    assert cached.latency_ms == 0.0


async def test_put_then_get_threat_verdict(fake_redis: Any) -> None:
    """После ``put(clean=False, signature=...)`` сигнатура сохраняется."""
    cache = AntivirusHashCache(fake_redis)
    payload = b"infected-bytes"
    verdict = AntivirusScanResult(
        clean=False, signature="Eicar-Test-Signature", backend="clamav_tcp"
    )

    await cache.put(payload, verdict)

    cached = await cache.get(payload)
    assert cached is not None
    assert cached.clean is False
    assert cached.signature == "Eicar-Test-Signature"
    assert cached.backend == "cache"


async def test_put_uses_default_ttl_when_not_specified() -> None:
    """``put`` без ``ttl`` пробрасывает ``default_ttl`` в ``Redis.set(ex=...)``."""
    client = _DictRedis()
    cache = AntivirusHashCache(client, default_ttl=120)
    await cache.put(b"x", AntivirusScanResult(clean=True))

    assert client.set_calls
    _, _, ex = client.set_calls[-1]
    assert ex == 120


async def test_put_custom_ttl_overrides_default() -> None:
    """Явный ``ttl`` имеет приоритет над ``default_ttl``."""
    client = _DictRedis()
    cache = AntivirusHashCache(client, default_ttl=120)
    await cache.put(b"x", AntivirusScanResult(clean=True), ttl=10)

    _, _, ex = client.set_calls[-1]
    assert ex == 10


async def test_key_uses_sha256_prefix() -> None:
    """Ключ имеет вид ``antivirus:hash:<sha256>``: разные payload -> разные ключи."""
    client = _DictRedis()
    cache = AntivirusHashCache(client)

    await cache.put(b"a", AntivirusScanResult(clean=True))
    await cache.put(b"b", AntivirusScanResult(clean=True))

    expected_a = "antivirus:hash:" + hashlib.sha256(b"a").hexdigest()
    expected_b = "antivirus:hash:" + hashlib.sha256(b"b").hexdigest()
    keys = {key for key, _, _ in client.set_calls}
    assert {expected_a, expected_b}.issubset(keys)


# ── Resilience ─────────────────────────────────────────────────────────────


async def test_get_returns_none_when_backend_raises() -> None:
    """Падение ``Redis.get`` не должно эскалировать — ``get`` возвращает ``None``."""
    client = AsyncMock()
    client.get.side_effect = ConnectionError("redis down")

    cache = AntivirusHashCache(client)
    assert await cache.get(b"x") is None


async def test_put_swallows_backend_error() -> None:
    """Падение ``Redis.set`` не должно эскалировать — ``put`` тихий."""
    client = AsyncMock()
    client.set.side_effect = ConnectionError("redis down")

    cache = AntivirusHashCache(client)
    # Не должно бросать
    await cache.put(b"x", AntivirusScanResult(clean=True))


async def test_get_returns_none_on_corrupt_entry() -> None:
    """Битые/несериализуемые байты в Redis -> ``get`` возвращает ``None``."""

    class _BrokenRedis:
        async def get(self, _key: str) -> bytes:
            return b"not-a-valid-json{{{"

    cache = AntivirusHashCache(_BrokenRedis())
    assert await cache.get(b"any") is None


async def test_get_uses_orjson_payload_layout(fake_redis: Any) -> None:
    """Запись в Redis сериализуется через orjson и обратно читается полностью."""
    cache = AntivirusHashCache(fake_redis)
    verdict = AntivirusScanResult(clean=False, signature="Foo")
    await cache.put(b"raw", verdict)

    raw = await fake_redis.get(
        "antivirus:hash:" + hashlib.sha256(b"raw").hexdigest()
    )
    assert raw is not None
    decoded = orjson.loads(raw)
    assert decoded == {"clean": False, "signature": "Foo"}
