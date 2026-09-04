"""Тесты GracefulShutdownMiddleware (W1+W2, ledger M5-#2 REOPENED).

Pure-ASGI контракт: pass-through в норме, 503 при drain, глобальный
счётчик in-flight, drain ждёт завершения in-flight ИЛИ timeout.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from src.backend.entrypoints.middlewares._registry import _INFLIGHT_COUNTER
from src.backend.entrypoints.middlewares.graceful_shutdown import (
    GracefulShutdownMiddleware,
    get_graceful_shutdown,
    get_in_flight_count,
)


def _http_scope() -> dict[str, str]:
    return {"type": "http", "method": "GET", "path": "/x"}


async def _ok_app(scope, receive, send):  # type: ignore[no-untyped-def]
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


_messages: list[dict[str, object]] = []


async def _receive() -> dict[str, str]:
    return {"type": "http.request", "body": b"", "more_body": False}


async def _send(message: dict[str, object]) -> None:
    _messages.append(message)


def _start_message() -> dict[str, object]:
    return next(m for m in _messages if m["type"] == "http.response.start")


@pytest.fixture(autouse=True)
def _reset_counter() -> None:
    _INFLIGHT_COUNTER.value = 0
    yield
    _INFLIGHT_COUNTER.value = 0


@pytest.mark.asyncio
async def test_pass_through_and_counter() -> None:
    """Нормальный запрос: 200, счётчик инкрементируется и возвращается в 0."""
    _messages.clear()
    mw = GracefulShutdownMiddleware(_ok_app)
    await mw(_http_scope(), _receive, _send)
    assert _start_message()["status"] == 200
    assert get_in_flight_count() == 0
    assert not mw._shutting_down


@pytest.mark.asyncio
async def test_503_after_drain_even_with_zero_inflight() -> None:
    """W1-фикс: drain() при 0 in-flight всё равно выставляет флаг → 503."""
    mw = GracefulShutdownMiddleware(_ok_app)
    await mw.drain()
    assert mw._shutting_down
    _messages.clear()
    await mw(_http_scope(), _receive, _send)
    assert _start_message()["status"] == 503
    body_msg = next(m for m in _messages if m["type"] == "http.response.body")
    assert json.loads(body_msg["body"])["error"] == "service_draining"


@pytest.mark.asyncio
async def test_drain_waits_for_inflight() -> None:
    """drain() ждёт завершения in-flight запроса."""
    gate = asyncio.Event()

    async def slow_app(scope, receive, send):  # type: ignore[no-untyped-def]
        await gate.wait()
        await _ok_app(scope, receive, send)

    mw = GracefulShutdownMiddleware(slow_app, drain_timeout=2.0)
    task = asyncio.create_task(mw(_http_scope(), _receive, _send))
    await asyncio.sleep(0)  # даём __call__ инкрементировать счётчик
    assert get_in_flight_count() == 1

    drain_task = asyncio.create_task(mw.drain())
    await asyncio.sleep(0.05)
    assert not drain_task.done()  # ждёт in-flight
    assert mw._shutting_down

    gate.set()
    await asyncio.wait_for(drain_task, timeout=1.0)
    await task
    assert get_in_flight_count() == 0


@pytest.mark.asyncio
async def test_drain_timeout_with_stuck_request() -> None:
    """Зависший in-flight → drain завершается по timeout, флаг выставлен."""
    gate = asyncio.Event()

    async def stuck_app(scope, receive, send):  # type: ignore[no-untyped-def]
        await gate.wait()
        await _ok_app(scope, receive, send)

    mw = GracefulShutdownMiddleware(stuck_app, drain_timeout=0.05)
    task = asyncio.create_task(mw(_http_scope(), _receive, _send))
    await asyncio.sleep(0)
    await asyncio.wait_for(mw.drain(), timeout=1.0)
    assert mw._shutting_down
    gate.set()
    await task


@pytest.mark.asyncio
async def test_non_http_scope_bypasses_gate() -> None:
    """WS/lifespan scope проходят без gate и без изменения счётчика."""
    mw = GracefulShutdownMiddleware(_ok_app)
    await mw.drain()  # даже в drain non-http проходит
    await mw({"type": "lifespan"}, _receive, _send)
    assert get_in_flight_count() == 0


@pytest.mark.asyncio
async def test_instance_registered_globally() -> None:
    """Регистрация инстанса доступна run_shutdown (step 0 drain hook)."""
    mw = GracefulShutdownMiddleware(_ok_app)
    assert get_graceful_shutdown() is mw


@pytest.mark.unit
@pytest.mark.asyncio
async def test_during_inflight_counter_visible() -> None:
    """Во время обработки счётчик > 0 (W2: телеметрия не мёртвая)."""
    seen: dict[str, int] = {}

    class Probe:
        def __init__(self, app: object) -> None:
            self.app = app

        async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
            seen["count"] = get_in_flight_count()
            await self.app(scope, receive, send)

    mw = GracefulShutdownMiddleware(Probe(_ok_app))
    await mw(_http_scope(), _receive, _send)
    assert seen["count"] == 1
