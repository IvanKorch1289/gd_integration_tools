"""Unit-тесты для :class:`RedisNxBackend` (V5 idempotency).

Покрытие:
* ``SET NX EX`` семантика — первый запрос резервирует ключ, второй
  получает «уже существует»;
* TTL передаётся в Redis (pending_ttl, response_ttl);
* ``get_stored_response`` возвращает ``JSONResponse`` с правильным
  payload + status_code;
* ``clear_idempotency_key`` снимает pending-блок.

Redis заменён in-memory заглушкой ``FakeRedis`` — fakeredis в проекте
не подключён, а тестировать нужно именно семантику команд.
"""

from __future__ import annotations

import asyncio
from typing import Any

import orjson
import pytest

from src.backend.entrypoints.middlewares.idempotency import (
    RedisNxBackend,
    build_idempotency_backend,
)


class _FakeRedis:
    """Минимальная in-memory заглушка Redis с поддержкой NX/EX."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.ttl: dict[str, int] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get(self, key: str) -> bytes | None:
        self.calls.append(("get", {"key": key}))
        return self.store.get(key)

    async def set(
        self,
        key: str,
        value: bytes | str,
        *,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool | None:
        self.calls.append(
            ("set", {"key": key, "value": value, "ex": ex, "nx": nx}),
        )
        if nx and key in self.store:
            return None
        self.store[key] = value if isinstance(value, bytes) else value.encode()
        if ex is not None:
            self.ttl[key] = ex
        return True

    async def delete(self, *keys: str) -> int:
        self.calls.append(("delete", {"keys": keys}))
        removed = 0
        for key in keys:
            if self.store.pop(key, None) is not None:
                removed += 1
            self.ttl.pop(key, None)
        return removed


@pytest.fixture
def fake_redis() -> _FakeRedis:
    return _FakeRedis()


@pytest.fixture
def backend(fake_redis: _FakeRedis) -> RedisNxBackend:
    return RedisNxBackend(fake_redis, pending_ttl=120, response_ttl=86400)


@pytest.mark.asyncio
async def test_store_idempotency_key_nx_first_call_reserves(
    backend: RedisNxBackend, fake_redis: _FakeRedis
) -> None:
    already_exists = await backend.store_idempotency_key("abc")
    assert already_exists is False
    set_call = next(c for c in fake_redis.calls if c[0] == "set")
    assert set_call[1]["nx"] is True
    assert set_call[1]["ex"] == 120
    assert set_call[1]["key"] == "idem:pending:abc"


@pytest.mark.asyncio
async def test_store_idempotency_key_second_call_reports_existing(
    backend: RedisNxBackend,
) -> None:
    first = await backend.store_idempotency_key("abc")
    second = await backend.store_idempotency_key("abc")
    assert first is False
    assert second is True


@pytest.mark.asyncio
async def test_store_response_data_writes_with_response_ttl(
    backend: RedisNxBackend, fake_redis: _FakeRedis
) -> None:
    await backend.store_response_data("abc", {"ok": True, "id": 42}, 201)
    body = fake_redis.store["idem:response:abc"]
    status = fake_redis.store["idem:response:abc:status"]
    assert orjson.loads(body) == {"ok": True, "id": 42}
    assert status == b"201"
    assert fake_redis.ttl["idem:response:abc"] == 86400
    assert fake_redis.ttl["idem:response:abc:status"] == 86400


@pytest.mark.asyncio
async def test_get_stored_response_returns_json_response(
    backend: RedisNxBackend,
) -> None:
    await backend.store_response_data("abc", {"value": 7}, 200)
    response = await backend.get_stored_response("abc")
    assert response is not None
    assert response.status_code == 200
    assert orjson.loads(response.body) == {"value": 7}


@pytest.mark.asyncio
async def test_get_stored_response_missing_returns_none(
    backend: RedisNxBackend,
) -> None:
    response = await backend.get_stored_response("missing")
    assert response is None


@pytest.mark.asyncio
async def test_clear_idempotency_key_removes_pending_block(
    backend: RedisNxBackend, fake_redis: _FakeRedis
) -> None:
    await backend.store_idempotency_key("abc")
    assert "idem:pending:abc" in fake_redis.store
    await backend.clear_idempotency_key("abc")
    assert "idem:pending:abc" not in fake_redis.store

    # После очистки ключ можно резервировать снова
    second = await backend.store_idempotency_key("abc")
    assert second is False


@pytest.mark.asyncio
async def test_concurrent_pending_only_one_wins(
    backend: RedisNxBackend,
) -> None:
    """V5: SET NX гарантирует, что только один из конкурентных запросов
    получит право обработать запрос; остальные → existing=True (→ 409).
    """
    results = await asyncio.gather(
        *[backend.store_idempotency_key("dup") for _ in range(5)]
    )
    # ровно один False (winner), остальные True (already exists)
    assert results.count(False) == 1
    assert results.count(True) == 4


def test_build_idempotency_backend_returns_redis_nx_when_provider_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """build_idempotency_backend строит RedisNxBackend поверх DI-провайдера.

    Сам ``redis_client`` не вызывается во время инстанцирования (lazy proxy).
    """
    backend = build_idempotency_backend()
    assert isinstance(backend, RedisNxBackend)


def test_build_idempotency_backend_fallback_when_di_broken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если DI-провайдер падает на импорте — fallback на MemoryBackend."""
    import sys

    from idempotency_header_middleware.backends.memory import MemoryBackend

    monkeypatch.setitem(
        sys.modules, "src.backend.core.di.providers", _RaisingModule()
    )
    backend = build_idempotency_backend()
    assert isinstance(backend, MemoryBackend)


class _RaisingModule:
    """Модуль-заглушка: любой attribute access падает."""

    def __getattr__(self, name: str) -> Any:
        raise RuntimeError(f"DI unavailable: {name}")
