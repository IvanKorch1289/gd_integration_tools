"""Unit-тесты для D-AUDIT-103: fallback Redis-down для middleware.

Покрывает:
* ``_LazyRedisProxy.get/set/delete`` при ConnectionError / TimeoutError /
  OSError — НЕ пробрасывают 5xx, возвращают degraded-ответы.
* ``RedisNxBackend.store_idempotency_key`` / ``get_stored_response`` /
  ``clear_idempotency_key`` / ``store_response_data`` при падающем Redis —
  НЕ пробрасывают исключения наружу.
* После восстановления Redis NX-семантика возобновляется с чистого
  состояния (никакого fallback-стейта не персистится в proxy).
* ``store_idempotency_key`` при nx=True в degraded-режиме возвращает
  ``False`` (treated as first request) — лучше пропустить дубль,
  чем вернуть 5xx или ошибочный 409.
* Non-transport ошибки (TypeError, RuntimeError, ValueError) НЕ маскируются.

См. V5 в ``CLAUDE.md`` и D-LESSON-3 (pending_ttl auto-release).
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.entrypoints.middlewares.idempotency import (
    RedisNxBackend,
    _LazyRedisProxy,
)


class _BrokenRedis:
    """Redis-клиент, у которого любой async-метод падает переданным исключением."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    async def get(self, key: str) -> bytes | None:
        raise self._exc

    async def set(
        self, key: str, value: bytes | str, *, ex: int | None = None, nx: bool = False,
    ) -> bool | None:
        raise self._exc

    async def delete(self, *keys: str) -> int:
        raise self._exc


class _HealthyRedis:
    """Минимальный Redis-клиент с NX/EX in-memory (для recovery-сценария)."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    async def get(self, key: str) -> bytes | None:
        return self.store.get(key)

    async def set(
        self, key: str, value: bytes | str, *, ex: int | None = None, nx: bool = False,
    ) -> bool | None:
        if nx and key in self.store:
            return None
        self.store[key] = value if isinstance(value, bytes) else value.encode()
        return True

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if self.store.pop(key, None) is not None:
                removed += 1
        return removed


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_connection_error() -> Any:
    import redis.exceptions

    return redis.exceptions.ConnectionError("Error 111 connecting: Connection refused")


def _make_timeout_error() -> Any:
    import redis.exceptions

    return redis.exceptions.TimeoutError("Timeout waiting for Redis")


@pytest.fixture
def proxy_broken_connection() -> _LazyRedisProxy:
    return _LazyRedisProxy(resolver=lambda: _BrokenRedis(_make_connection_error()))


@pytest.fixture
def proxy_broken_timeout() -> _LazyRedisProxy:
    return _LazyRedisProxy(resolver=lambda: _BrokenRedis(_make_timeout_error()))


@pytest.fixture
def proxy_broken_os() -> _LazyRedisProxy:
    return _LazyRedisProxy(resolver=lambda: _BrokenRedis(OSError("net unreachable")))


@pytest.fixture
def backend_broken_connection(proxy_broken_connection: _LazyRedisProxy) -> RedisNxBackend:
    """Backend с падающим Redis через ``_LazyRedisProxy`` (как в prod)."""
    return RedisNxBackend(proxy_broken_connection)


@pytest.fixture
def backend_broken_timeout(proxy_broken_timeout: _LazyRedisProxy) -> RedisNxBackend:
    return RedisNxBackend(proxy_broken_timeout)


@pytest.fixture
def backend_broken_os(proxy_broken_os: _LazyRedisProxy) -> RedisNxBackend:
    return RedisNxBackend(proxy_broken_os)


@pytest.fixture
def switching_resolver() -> tuple[_LazyRedisProxy, _HealthyRedis, dict[str, bool]]:
    """Proxy, переключающийся между broken и healthy между вызовами."""
    healthy = _HealthyRedis()
    state: dict[str, bool] = {"use_broken": True}

    def resolver() -> Any:
        if state["use_broken"]:
            return _BrokenRedis(_make_connection_error())
        return healthy

    return _LazyRedisProxy(resolver=resolver), healthy, state


# ---------------------------------------------------------------------------
# _LazyRedisProxy: degraded mode на каждом из методов
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc_factory",
    [
        _make_connection_error,
        _make_timeout_error,
        lambda: OSError("net"),
    ],
    ids=["ConnectionError", "TimeoutError", "OSError"],
)
async def test_proxy_get_returns_none_on_redis_down(exc_factory: Any) -> None:
    """D-AUDIT-103: get при недоступном Redis возвращает None (cache miss)."""
    proxy = _LazyRedisProxy(resolver=lambda: _BrokenRedis(exc_factory()))

    result = await proxy.get("any:key")

    assert result is None


@pytest.mark.asyncio
async def test_proxy_set_returns_true_on_redis_down() -> None:
    """D-AUDIT-103: set при недоступном Redis возвращает True (degraded success)."""
    proxy = _LazyRedisProxy(resolver=lambda: _BrokenRedis(_make_connection_error()))

    result = await proxy.set("any:key", b"value", ex=120, nx=True)

    assert result is True


@pytest.mark.asyncio
async def test_proxy_delete_returns_zero_on_redis_down() -> None:
    """D-AUDIT-103: delete при недоступном Redis возвращает 0 (no-op)."""
    proxy = _LazyRedisProxy(resolver=lambda: _BrokenRedis(_make_connection_error()))

    result = await proxy.delete("any:key")

    assert result == 0


# ---------------------------------------------------------------------------
# RedisNxBackend: end-to-end через middleware-контракт (prod config: backend(_LazyRedisProxy))
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_idempotency_key_does_not_5xx_when_redis_down(
    backend_broken_connection: RedisNxBackend,
) -> None:
    """D-AUDIT-103: ``store_idempotency_key`` не пробрасывает 5xx наружу.

    При падающем Redis middleware должен принять запрос как «первый»,
    вернуть ``False`` (→ 200 OK), а не пробросить ``ConnectionError``.
    """
    result = await backend_broken_connection.store_idempotency_key("abc")

    assert result is False


@pytest.mark.asyncio
async def test_store_idempotency_key_does_not_5xx_on_timeout(
    backend_broken_timeout: RedisNxBackend,
) -> None:
    """D-AUDIT-103: TimeoutError также глушится на уровне proxy."""
    result = await backend_broken_timeout.store_idempotency_key("abc")

    assert result is False


@pytest.mark.asyncio
async def test_store_idempotency_key_does_not_5xx_on_os_error(
    backend_broken_os: RedisNxBackend,
) -> None:
    """D-AUDIT-103: OSError (network unreachable) также глушится."""
    result = await backend_broken_os.store_idempotency_key("abc")

    assert result is False


@pytest.mark.asyncio
async def test_get_stored_response_returns_none_when_redis_down(
    backend_broken_connection: RedisNxBackend,
) -> None:
    """D-AUDIT-103: ``get_stored_response`` возвращает None (cache miss),
    запрос проходит как первый, а не 5xx.
    """
    result = await backend_broken_connection.get_stored_response("abc")

    assert result is None


@pytest.mark.asyncio
async def test_store_response_data_swallows_redis_down(
    backend_broken_connection: RedisNxBackend,
) -> None:
    """D-AUDIT-103: ``store_response_data`` не пробрасывает 5xx наружу."""
    # Strict: NO exception.
    await backend_broken_connection.store_response_data("abc", {"ok": True}, 200)


@pytest.mark.asyncio
async def test_clear_idempotency_key_swallows_redis_down(
    backend_broken_connection: RedisNxBackend,
) -> None:
    """D-AUDIT-103: ``clear_idempotency_key`` не пробрасывает 5xx наружу."""
    # Strict: NO exception.
    await backend_broken_connection.clear_idempotency_key("abc")


@pytest.mark.asyncio
async def test_backend_no_exception_propagated_when_redis_down(
    backend_broken_connection: RedisNxBackend,
) -> None:
    """D-AUDIT-103: полный happy-path во время простоя Redis.

    Использует ``pytest.raises(None)``-паттерн — если исключение
    всплывёт, тест провалится. Сейчас просто последовательность
    вызовов, которая не должна бросать.
    """
    # Strict: NO exception — все 4 операции на падающем Redis.
    assert await backend_broken_connection.store_idempotency_key("k") is False
    assert await backend_broken_connection.get_stored_response("k") is None
    await backend_broken_connection.store_response_data("k", {"ok": 1}, 200)
    await backend_broken_connection.clear_idempotency_key("k")


# ---------------------------------------------------------------------------
# Recovery: NX-семантика возобновляется после возврата Redis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nx_semantics_resume_after_redis_recovery(
    switching_resolver: tuple[_LazyRedisProxy, _HealthyRedis, dict[str, bool]],
) -> None:
    """D-AUDIT-103: после возврата Redis NX-блокировка работает штатно.

    Проверяет, что degraded-режим не сохраняет «грязное» состояние:
    proxy ничего не пишет в fallback (его нет) — и при возобновлении
    Redis NX-логика чистая.
    """
    proxy, healthy, state = switching_resolver
    backend = RedisNxBackend(proxy)

    # 1) Redis DOWN: запрос проходит, не 5xx.
    state["use_broken"] = True
    first = await backend.store_idempotency_key("abc")
    assert first is False

    # 2) Redis ВОЗВРАЩАЕТСЯ: первый запрос резервирует ключ.
    state["use_broken"] = False
    second = await backend.store_idempotency_key("abc")
    assert second is False
    assert "idem:pending:abc" in healthy.store

    # 3) Третий запрос с тем же ключом — NX видит существующий, → 409.
    third = await backend.store_idempotency_key("abc")
    assert third is True


@pytest.mark.asyncio
async def test_get_stored_response_falls_back_to_none_then_redis(
    switching_resolver: tuple[_LazyRedisProxy, _HealthyRedis, dict[str, bool]],
) -> None:
    """D-AUDIT-103: после recovery get_stored_response снова видит Redis-данные."""
    proxy, _healthy, state = switching_resolver
    backend = RedisNxBackend(proxy)

    # Redis DOWN → None (cache miss).
    state["use_broken"] = True
    assert await backend.get_stored_response("abc") is None

    # Redis возвращается → пишем ответ напрямую в backend.
    state["use_broken"] = False
    await backend.store_response_data("abc", {"recovered": True}, 201)

    # Теперь get должен вернуть JSONResponse.
    response = await backend.get_stored_response("abc")
    assert response is not None
    assert response.status_code == 201
    import orjson

    assert orjson.loads(response.body) == {"recovered": True}


# ---------------------------------------------------------------------------
# Negative: не-транспортные ошибки НЕ маскируются
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_non_transport_exception_is_propagated() -> None:
    """D-AUDIT-103: только транспортные ошибки глушатся; баги (TypeError)
    пробрасываются — иначе скрыли бы регрессию.
    """
    proxy = _LazyRedisProxy(resolver=lambda: _RaisingGetClient())

    with pytest.raises(TypeError, match="bug"):
        await proxy.get("any:key")


@pytest.mark.asyncio
async def test_set_non_transport_exception_is_propagated() -> None:
    proxy = _LazyRedisProxy(resolver=lambda: _RaisingSetClient())

    with pytest.raises(RuntimeError, match="boom"):
        await proxy.set("any:key", b"value")


@pytest.mark.asyncio
async def test_delete_non_transport_exception_is_propagated() -> None:
    proxy = _LazyRedisProxy(resolver=lambda: _RaisingDeleteClient())

    with pytest.raises(ValueError, match="nope"):
        await proxy.delete("any:key")


# ---------------------------------------------------------------------------
# Helpers (non-transport raising clients)
# ---------------------------------------------------------------------------


class _RaisingGetClient:
    async def get(self, key: str) -> bytes | None:
        raise TypeError("bug")

    async def set(
        self, key: str, value: bytes | str, *, ex: int | None = None, nx: bool = False,
    ) -> bool | None:
        return True

    async def delete(self, *keys: str) -> int:
        return 0


class _RaisingSetClient:
    async def get(self, key: str) -> bytes | None:
        return None

    async def set(
        self, key: str, value: bytes | str, *, ex: int | None = None, nx: bool = False,
    ) -> bool | None:
        raise RuntimeError("boom")

    async def delete(self, *keys: str) -> int:
        return 0


class _RaisingDeleteClient:
    async def get(self, key: str) -> bytes | None:
        return None

    async def set(
        self, key: str, value: bytes | str, *, ex: int | None = None, nx: bool = False,
    ) -> bool | None:
        return True

    async def delete(self, *keys: str) -> int:
        raise ValueError("nope")
