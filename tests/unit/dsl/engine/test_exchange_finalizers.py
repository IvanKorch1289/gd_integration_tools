"""Тесты Exchange.add_finalizer / run_finalizers (FIX-C1-BROWSER-CONTEXT-LEAK).

Проверяют контракт cleanup-механизма: LIFO-порядок, изоляция ошибок,
поддержка sync/async колбэков, idempotency.
"""

# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message


def _exchange() -> Exchange:
    return Exchange(in_message=Message(body={}))


@pytest.mark.asyncio
async def test_sync_finalizer_runs() -> None:
    ex = _exchange()
    calls: list[str] = []
    ex.add_finalizer(lambda: calls.append("sync"))
    await ex.run_finalizers()
    assert calls == ["sync"]
    # idempotent — повторный вызов no-op
    await ex.run_finalizers()
    assert calls == ["sync"]


@pytest.mark.asyncio
async def test_async_finalizer_awaited() -> None:
    ex = _exchange()
    calls: list[str] = []

    async def _afn() -> None:
        calls.append("async")

    ex.add_finalizer(_afn)
    await ex.run_finalizers()
    assert calls == ["async"]


@pytest.mark.asyncio
async def test_finalizers_run_lifo_order() -> None:
    ex = _exchange()
    calls: list[int] = []
    for i in range(3):
        ex.add_finalizer(lambda i=i: calls.append(i))
    await ex.run_finalizers()
    assert calls == [2, 1, 0]


@pytest.mark.asyncio
async def test_failing_finalizer_does_not_block_others() -> None:
    ex = _exchange()
    calls: list[str] = []

    def _boom() -> None:
        calls.append("boom")
        raise RuntimeError("oops")

    ex.add_finalizer(lambda: calls.append("first"))
    ex.add_finalizer(_boom)
    ex.add_finalizer(lambda: calls.append("last"))
    # LIFO: last → boom → first; boom не должен прервать цепочку.
    await ex.run_finalizers()
    assert calls == ["last", "boom", "first"]


@pytest.mark.asyncio
async def test_run_finalizers_without_any_registered_is_noop() -> None:
    ex = _exchange()
    await ex.run_finalizers()  # не должно бросать
    assert "_finalizers" not in ex.properties


@pytest.mark.asyncio
async def test_clone_does_not_inherit_finalizers() -> None:
    """Клон не должен дублировать cleanup-хуки родителя (no double-release)."""
    ex = _exchange()
    ex.add_finalizer(lambda: None)
    ex.set_property("rpa.page", "shared-page")
    cloned = ex.clone()
    assert cloned.properties["rpa.page"] == "shared-page"
    assert "_finalizers" not in cloned.properties
    # Родитель по-прежнему владеет своим finalizer.
    assert "_finalizers" in ex.properties
