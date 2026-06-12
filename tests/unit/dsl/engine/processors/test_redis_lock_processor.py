"""S84 W3 — тесты RedisLockProcessor (redis_lock DSL step).

Сценарии:
    * Lock acquired → ``_lock_acquired=True``, pipeline продолжается.
    * Lock contention + fail_on_contention=True (default) → ``exchange.fail``.
    * Lock contention + fail_on_contention=False → pipeline идёт, ``_lock_acquired=False``.
    * RedisLock import error → ``exchange.fail``.
    * Acquire exception → ``exchange.fail``.
    * ``to_spec()`` сериализует все параметры.
    * Custom key_prefix → попадает в RedisLock.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.redis_lock_processor import (
    RedisLockProcessor,
)


def _exchange_with() -> Exchange[Any]:
    return Exchange(in_message=Message(body=b"", headers={}))


def _patch_redis_lock(
    *, acquire_return: bool | Exception, redis_lock_cls_mock: Any | None = None
) -> Any:
    """Возвращает MagicMock для ``RedisLock`` class.

    Каждый инстанс имеет ``acquire`` (AsyncMock) с указанным return.
    """
    if redis_lock_cls_mock is not None:
        return redis_lock_cls_mock

    async def _acquire(*_args: Any, **_kwargs: Any) -> Any:
        if isinstance(acquire_return, Exception):
            raise acquire_return
        return acquire_return

    fake_cls = MagicMock()
    fake_instance = MagicMock()
    fake_instance.acquire = _acquire
    fake_cls.return_value = fake_instance
    return fake_cls


# ─── Happy path ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_redis_lock_acquired_writes_property() -> None:
    """Lock acquired → ``_lock_acquired=True``, pipeline не прерывается."""
    proc = RedisLockProcessor(key="orders.cron", ttl_seconds=30)
    ex = _exchange_with()

    with patch(
        "src.backend.infrastructure.clients.storage.redis_lock.RedisLock",
        new=_patch_redis_lock(acquire_return=True),
    ):
        await proc.process(ex, context=MagicMock())

    assert ex.properties.get("_lock_acquired") is True
    # exchange НЕ failed.
    assert ex.error is None


@pytest.mark.asyncio
async def test_redis_lock_acquired_with_blocking_timeout() -> None:
    """blocking_timeout=0 → non-blocking acquire."""
    proc = RedisLockProcessor(
        key="orders.cron", ttl_seconds=60, blocking_timeout=0.0
    )
    ex = _exchange_with()

    fake_cls = MagicMock()
    fake_instance = MagicMock()

    async def _acquire(*, blocking_timeout: float | None) -> bool:
        # ``blocking_timeout`` пробрасывается в RedisLock.acquire.
        assert blocking_timeout == 0.0
        return True

    fake_instance.acquire = _acquire
    fake_cls.return_value = fake_instance

    with patch(
        "src.backend.infrastructure.clients.storage.redis_lock.RedisLock",
        new=fake_cls,
    ):
        await proc.process(ex, context=MagicMock())

    assert ex.properties.get("_lock_acquired") is True


# ─── Contention paths ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_redis_lock_contention_fails_exchange_by_default() -> None:
    """Lock не получен + fail_on_contention=True (default) → ``exchange.fail``."""
    proc = RedisLockProcessor(key="busy.resource")
    ex = _exchange_with()

    with patch(
        "src.backend.infrastructure.clients.storage.redis_lock.RedisLock",
        new=_patch_redis_lock(acquire_return=False),
    ):
        await proc.process(ex, context=MagicMock())

    assert ex.properties.get("_lock_acquired") is False
    assert ex.error is not None
    assert "busy.resource" in ex.error


@pytest.mark.asyncio
async def test_redis_lock_contention_continues_when_fail_disabled() -> None:
    """Lock не получен + fail_on_contention=False → pipeline продолжается."""
    proc = RedisLockProcessor(key="ab_test.run", fail_on_contention=False)
    ex = _exchange_with()

    with patch(
        "src.backend.infrastructure.clients.storage.redis_lock.RedisLock",
        new=_patch_redis_lock(acquire_return=False),
    ):
        await proc.process(ex, context=MagicMock())

    assert ex.properties.get("_lock_acquired") is False
    # Pipeline НЕ failed — downstream может принять решение на основе
    # ``_lock_acquired``.
    assert ex.error is None


# ─── Custom key_prefix ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_redis_lock_custom_key_prefix() -> None:
    """``key_prefix="etl"`` → передаётся в RedisLock constructor."""
    proc = RedisLockProcessor(key="backup", key_prefix="etl")
    ex = _exchange_with()

    fake_cls = MagicMock()
    fake_instance = MagicMock()
    fake_instance.acquire = AsyncMock(return_value=True)
    fake_cls.return_value = fake_instance

    with patch(
        "src.backend.infrastructure.clients.storage.redis_lock.RedisLock",
        new=fake_cls,
    ):
        await proc.process(ex, context=MagicMock())

    fake_cls.assert_called_once_with(
        "backup", ttl_seconds=60, key_prefix="etl"
    )


# ─── Failure paths ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_redis_lock_acquire_exception_fails_exchange() -> None:
    """``acquire`` бросает исключение → ``exchange.fail``."""
    proc = RedisLockProcessor(key="problematic")
    ex = _exchange_with()

    with patch(
        "src.backend.infrastructure.clients.storage.redis_lock.RedisLock",
        new=_patch_redis_lock(acquire_return=RuntimeError("redis connection lost")),
    ):
        await proc.process(ex, context=MagicMock())

    assert ex.error is not None
    assert "redis connection lost" in ex.error
    assert "_lock_acquired" not in ex.properties


@pytest.mark.asyncio
async def test_redis_lock_import_error_fails_exchange() -> None:
    """RedisLock import failure → ``exchange.fail``."""
    proc = RedisLockProcessor(key="any")
    ex = _exchange_with()

    # Подменяем __import__ для модуля, чтобы from import дал ImportError.
    import builtins

    real_import = builtins.__import__

    def _import(name: str, *args: Any, **kwargs: Any) -> Any:
        if "redis_lock" in name and "infrastructure" in name:
            raise ImportError("simulated: redis not installed")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=_import):
        await proc.process(ex, context=MagicMock())

    assert ex.error is not None
    assert "redis dependencies not installed" in ex.error or "ImportError" in ex.error


# ─── to_spec serialization ─────────────────────────────────────────────────


def test_redis_lock_to_spec_minimal() -> None:
    """Default значения опускаются в spec."""
    proc = RedisLockProcessor(key="x")
    spec = proc.to_spec()
    assert spec == {
        "redis_lock": {
            "key": "x",
            "ttl_seconds": 60,
        }
    }


def test_redis_lock_to_spec_full() -> None:
    """Все параметры сериализуются."""
    proc = RedisLockProcessor(
        key="etl",
        ttl_seconds=300,
        blocking_timeout=10.0,
        fail_on_contention=False,
        key_prefix="etl",
    )
    spec = proc.to_spec()
    assert spec == {
        "redis_lock": {
            "key": "etl",
            "ttl_seconds": 300,
            "blocking_timeout": 10.0,
            "fail_on_contention": False,
            "key_prefix": "etl",
        }
    }
