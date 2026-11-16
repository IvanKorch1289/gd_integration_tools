"""Regression tests для JWTBlocklist: блокировка без deadlock между loop'ами.

История (Sprint 215+): в ``InMemoryJwtBlacklist`` использовался
``threading.Lock()`` в async-методах — это блокировало event loop на каждой
проверке blacklist, и lock заменили на ``asyncio.Lock()``.

Волна 33 (полная регрессия): ``asyncio.Lock`` привязывается к первому
event loop, который его ``await``'ит. При обращении к тому же объекту из
другого loop (sync-middleware в ThreadPoolExecutor, отдельные loop'и в
тестах) ожидание блокировки **зависало навсегда** — тест на thread-safety
падал по таймауту 600 s.

Решение: критическая секция синхронная (операции с ``dict``), поэтому
защита переведена на ``threading.Lock``: блокировка event loop минимальна
(микросекунды), а объект пригоден из любого loop'а и потока.

Тесты проверяют что:
1. используется ``threading.Lock`` (loop-agnostic);
2. async API (revoke/unvoke/is_revoked/clear) работает корректно;
3. конкурентный доступ из **разных** event loop'ов не деградирует и не
   зависает (регрессия волны 33).
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from src.backend.services.security.facade import _InMemoryJwtBlacklist


class TestInMemoryJWTBlacklistLockType:
    """Verify threading.Lock (loop-agnostic, без deadlock между loop'ами)."""

    def test_lock_is_threading_lock(self) -> None:
        bl = _InMemoryJwtBlacklist()
        assert isinstance(bl._lock, threading.Lock), (
            f"_InMemoryJwtBlacklist._lock должен быть threading.Lock, "
            f"получено {type(bl._lock).__name__}. "
            f"asyncio.Lock привязывается к первому event loop и зависает "
            f"при обращении из другого loop (волна 33)."
        )


class TestInMemoryJWTBlacklistAsyncAPI:
    """Verify async revoke/unvoke/is_revoked работают корректно."""

    @pytest.mark.asyncio
    async def test_revoke_then_is_revoked(self) -> None:
        bl = _InMemoryJwtBlacklist()
        await bl.revoke("jti-1", expires_at=int(time.time()) + 3600)
        assert await bl.is_revoked("jti-1") is True

    @pytest.mark.asyncio
    async def test_revoke_unrevoke_roundtrip(self) -> None:
        bl = _InMemoryJwtBlacklist()
        await bl.revoke("jti-2", expires_at=int(time.time()) + 3600)
        assert await bl.is_revoked("jti-2") is True
        await bl.unrevoke("jti-2")
        assert await bl.is_revoked("jti-2") is False

    @pytest.mark.asyncio
    async def test_is_revoked_for_unknown_returns_false(self) -> None:
        bl = _InMemoryJwtBlacklist()
        assert await bl.is_revoked("never-revoked") is False

    @pytest.mark.asyncio
    async def test_concurrent_revoke_does_not_corrupt(self) -> None:
        """Stress test: 50 concurrent revokes на 50 разных JTI."""
        bl = _InMemoryJwtBlacklist()
        tasks = [
            bl.revoke(f"jti-{i}", expires_at=int(time.time()) + 3600) for i in range(50)
        ]
        await asyncio.gather(*tasks)

        # Verify все 50 — revoked
        for i in range(50):
            assert await bl.is_revoked(f"jti-{i}") is True


def test_access_from_multiple_event_loops_does_not_hang() -> None:
    """Один blacklist из нескольких loop'ов: без зависания (регрессия 33).

    С ``asyncio.Lock`` второй loop ждал бы блокировку, которую держит
    первый, — до бесконечности. С ``threading.Lock`` обе операции
    завершаются.
    """
    bl = _InMemoryJwtBlacklist()
    errors: list[Exception] = []

    def worker(index: int) -> None:
        try:
            loop = asyncio.new_event_loop()
            try:
                for i in range(20):
                    jti = f"jti_{index}_{i}"
                    loop.run_until_complete(bl.revoke(jti, 9999999999))
                    assert loop.run_until_complete(bl.is_revoked(jti)) is True
                    loop.run_until_complete(bl.unrevoke(jti))
            finally:
                loop.close()
        except Exception as exc:  # pragma: no cover — диагностика сбоя
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive(), "поток завис на блокировке blacklist"

    assert errors == [], f"Ошибки конкурентного доступа: {errors}"
