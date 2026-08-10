"""Regression test for D-AUDIT-98 (S183 W1.1): CapabilityGate cache race.

The previous implementation of ``CapabilityGate._cache`` /
``_tenant_cache`` mutated plain ``dict`` instances without any
synchronization. ``_invalidate_plugin`` rebuilt the cache via
``{k: v for k, v in cache.items() if ...}`` while concurrent
``_cache_granted`` calls performed ``len(cache)`` / ``next(iter(cache))``
/ ``cache.pop()`` / ``cache[key] = ...``. Under load this raised
``RuntimeError: dictionary changed size during iteration``.

This test asserts the post-fix invariants:

1. Concurrent ``_cache_granted`` + ``_invalidate_plugin`` never raises
   ``RuntimeError`` (no ``dict`` resize during iteration).
2. Final ``_cache`` size never exceeds ``_lru_size`` (LRU invariant
   preserved across all mutations).
3. ``_tenant_cache`` survives concurrent ``_tenant_cache_granted`` +
   ``_invalidate_tenant`` storms.
4. The gate remains usable after a storm — ``check`` / ``check_tenant``
   still return correct granted/denied outcomes for declared capabilities.

The test would FAIL on the pre-fix code (would raise
``RuntimeError`` from at least one task in the gather) and PASS on the
post-fix code.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from src.backend.core.security.capabilities import CapabilityGate, CapabilityRef

# ── Test helpers ────────────────────────────────────────────────────


def _make_gate(*, lru_size: int = 32) -> CapabilityGate:
    """Gate with small LRU to force eviction under load."""
    return CapabilityGate(lru_size=lru_size)


def _declared_ref(name: str = "db.read", scope: str = "credit_db") -> CapabilityRef:
    return CapabilityRef(name=name, scope=scope)


# ── Sync-threaded storm (mirrors FastAPI worker pool) ───────────────


class TestCacheMixinRaceSync:
    """Concurrent grant + invalidate from threads."""

    def test_grant_and_invalidate_plugin_no_runtime_error(self) -> None:
        """``_cache_granted`` + ``_invalidate_plugin`` must not raise.

        Pre-fix: at least one task raised
        ``RuntimeError: dictionary changed size during iteration``.
        """
        gate = _make_gate(lru_size=64)
        errors: list[BaseException] = []
        gate_lock = threading.Lock()

        def worker(worker_id: int) -> None:
            try:
                for i in range(150):
                    key = (f"plugin_{worker_id % 8}", "db.read", f"scope_{i % 16}")
                    gate._cache_granted(key)
                    if i % 7 == 0:
                        gate._invalidate_plugin(f"plugin_{worker_id % 8}")
            except BaseException as exc:
                with gate_lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], (
            f"Expected no errors, got {len(errors)}; "
            f"first: {type(errors[0]).__name__}: {errors[0]}"
        )

    def test_cache_size_invariant_under_storm(self) -> None:
        """``len(self._cache) <= lru_size`` must hold post-storm and threads must NOT raise.

        Pre-fix the lock-free LRU eviction raised
        ``RuntimeError: dictionary changed size during iteration`` from
        ``_invalidate_plugin`` while concurrent writers mutated the dict.
        """
        import time

        lru = 32
        gate = _make_gate(lru_size=lru)
        stop = threading.Event()
        errors: list[BaseException] = []
        err_lock = threading.Lock()

        def writer() -> None:
            i = 0
            try:
                while not stop.is_set():
                    gate._cache_granted((f"p{i % 4}", "db.read", f"s{i % 64}"))
                    i += 1
            except BaseException as exc:
                with err_lock:
                    errors.append(exc)

        def invalidator() -> None:
            try:
                while not stop.is_set():
                    gate._invalidate_plugin("p0")
            except BaseException as exc:
                with err_lock:
                    errors.append(exc)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=writer),
            threading.Thread(target=invalidator),
        ]
        for t in threads:
            t.start()
        time.sleep(0.2)
        stop.set()
        for t in threads:
            t.join()

        assert errors == [], (
            f"Threads raised during storm: {[type(e).__name__ for e in errors]}; "
            f"first: {type(errors[0]).__name__}: {errors[0]}"
        )
        assert len(gate._cache) <= lru, (
            f"_cache grew past lru_size: {len(gate._cache)} > {lru}"
        )

    def test_gate_remains_callable_after_storm(self) -> None:
        """``check()`` keeps correct semantics after concurrent grant+invalidate.

        Pre-fix the storm could leave the cache in a state where a
        declared capability check unexpectedly raised — or where an
        undeclared capability incorrectly returned granted from stale cache.
        Threads must not raise ``RuntimeError`` during the storm.
        """

        gate = _make_gate(lru_size=128)
        gate.declare("plug", [_declared_ref()])

        stop = threading.Event()
        errors: list[BaseException] = []
        err_lock = threading.Lock()

        def storm() -> None:
            i = 0
            try:
                while not stop.is_set():
                    gate._cache_granted(("plug", "db.read", f"s{i % 32}"))
                    if i % 5 == 0:
                        gate._invalidate_plugin("plug")
                    i += 1
            except BaseException as exc:
                with err_lock:
                    errors.append(exc)

        t = threading.Thread(target=storm)
        t.start()
        try:
            # Declared capability → must succeed, not raise.
            for _ in range(50):
                gate.check("plug", "db.read", "credit_db")
        finally:
            stop.set()
            t.join()

        assert errors == [], (
            f"Storm thread raised: {[type(e).__name__ for e in errors]}; "
            f"first: {type(errors[0]).__name__}: {errors[0]}"
        )

        # Undeclared capability for a fresh plugin → must raise.
        with pytest.raises(Exception):  # CapabilityDeniedError
            gate.check("undeclared_plugin", "db.read", "credit_db")


# ── Async storm (mirrors FastAPI async handlers) ─────────────────────


class TestCheckMixinRaceAsync:
    """Concurrent async ``check`` + invalidate via asyncio.gather."""

    @pytest.mark.asyncio
    async def test_check_tenant_storm_no_runtime_error(self) -> None:
        """Concurrent ``check_tenant`` + ``_invalidate_tenant`` is safe."""
        gate = _make_gate(lru_size=64)
        errors: list[BaseException] = []
        errors_lock = asyncio.Lock()

        async def check_task(task_id: int) -> None:
            try:
                for i in range(200):
                    tenant = f"tenant_{task_id % 4}"
                    await asyncio.sleep(0)
                    gate.check_tenant("db.read", tenant, "plug", "credit_db")
            except BaseException as exc:
                async with errors_lock:
                    errors.append(exc)

        async def invalidate_task() -> None:
            try:
                for i in range(200):
                    await asyncio.sleep(0)
                    gate._invalidate_tenant(f"tenant_{i % 4}")
            except BaseException as exc:
                async with errors_lock:
                    errors.append(exc)

        await asyncio.gather(*(check_task(i) for i in range(8)), invalidate_task())

        assert errors == [], (
            f"Expected no async errors, got {len(errors)}; "
            f"first: {type(errors[0]).__name__}: {errors[0]}"
        )

    @pytest.mark.asyncio
    async def test_tenant_cache_size_invariant_async(self) -> None:
        """Per-tenant cache never exceeds ``lru_size`` under async storm."""
        lru = 16
        gate = _make_gate(lru_size=lru)
        stop = asyncio.Event()

        async def writer() -> None:
            i = 0
            while not stop.is_set():
                gate._tenant_cache_granted(
                    (f"t{i % 2}", "plug", "db.read", f"s{i % 32}")
                )
                i += 1
                await asyncio.sleep(0)

        async def invalidator() -> None:
            while not stop.is_set():
                gate._invalidate_tenant("t0")
                await asyncio.sleep(0)

        tasks = [
            asyncio.create_task(writer()),
            asyncio.create_task(writer()),
            asyncio.create_task(invalidator()),
        ]
        await asyncio.sleep(0.1)
        stop.set()
        await asyncio.gather(*tasks)

        assert len(gate._tenant_cache) <= lru, (
            f"_tenant_cache grew past lru_size: {len(gate._tenant_cache)} > {lru}"
        )

    @pytest.mark.asyncio
    async def test_check_tenant_correctness_under_storm(self) -> None:
        """``check_tenant`` returns the right bool after a concurrent storm.

        Pre-fix the storm could raise
        ``RuntimeError: dictionary changed size during iteration`` from
        ``_invalidate_tenant`` while concurrent ``check_tenant`` writes
        to ``self._tenant_cache[key]``.
        """
        gate = _make_gate(lru_size=128)
        gate.declare_tenant(_declared_ref(), "tenant_a", "plug")

        stop = asyncio.Event()
        errors: list[BaseException] = []
        err_lock = asyncio.Lock()

        async def storm() -> None:
            i = 0
            try:
                while not stop.is_set():
                    gate._tenant_cache_granted(
                        ("tenant_a", "plug", "db.read", f"s{i % 32}")
                    )
                    if i % 5 == 0:
                        gate._invalidate_tenant("tenant_a", "plug")
                    i += 1
                    await asyncio.sleep(0)
            except BaseException as exc:
                async with err_lock:
                    errors.append(exc)

        async def checker() -> None:
            try:
                while not stop.is_set():
                    gate.check_tenant("db.read", "tenant_a", "plug", "credit_db")
                    await asyncio.sleep(0)
            except BaseException as exc:
                async with err_lock:
                    errors.append(exc)

        tasks = [asyncio.create_task(storm()), asyncio.create_task(checker())]
        try:
            # Declared → True (not raise, not None).
            results = [
                gate.check_tenant("db.read", "tenant_a", "plug", "credit_db")
                for _ in range(50)
            ]
        finally:
            stop.set()
            await asyncio.gather(*tasks)

        assert errors == [], (
            f"Storm/checker tasks raised: {[type(e).__name__ for e in errors]}; "
            f"first: {type(errors[0]).__name__}: {errors[0]}"
        )
        assert all(r is True for r in results), results

        # Undeclared (tenant, principal) → False.
        assert (
            gate.check_tenant("db.read", "tenant_undeclared", "plug", "credit_db")
            is False
        )


# ── Direct mixin invariants ─────────────────────────────────────────


class TestCacheLRUEvictionContract:
    """LRU-eviction contract must survive concurrent writes."""

    def test_lru_eviction_within_limit_under_threads(self) -> None:
        """``len(self._cache) <= lru_size`` after concurrent writers."""
        lru = 8
        gate = _make_gate(lru_size=lru)

        def writer(start: int) -> None:
            for i in range(start, start + 500):
                gate._cache_granted(("p", "c", f"s{i % 100}"))

        threads = [threading.Thread(target=writer, args=(i * 500,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(gate._cache) <= lru


# ── Lock-internals sanity ────────────────────────────────────────────


class TestLockPresent:
    """The lock attribute must exist and be a ``threading.Lock``."""

    def test_gate_has_lock(self) -> None:
        """``CapabilityGate._lock`` is a ``threading.Lock`` instance."""
        gate = CapabilityGate()
        assert isinstance(gate._lock, type(threading.Lock()))

    def test_lock_acquired_state_after_grant(self) -> None:
        """Lock must NOT remain held after a single cached call returns."""
        gate = CapabilityGate()
        gate._cache_granted(("p", "c", "s"))
        # If the lock leaked, this would block forever; pytest timeout
        # would catch it. We assert non-blocking acquire instead.
        assert gate._lock.acquire(blocking=False) is True
        gate._lock.release()
