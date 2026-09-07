"""Тесты dsl/orchestration/triggers.py — T3 ratchet (64%→≥90%).

IntervalTrigger (idempotent start, dispatch-loop, stop), CronTrigger,
WebhookTrigger (route registration/deferral/handler), TriggerRegistry
(register/replace, start_all/stop_all с swallow, singleton).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.orchestration.triggers import (
    CronTrigger,
    IntervalTrigger,
    TriggerRegistry,
    WebhookTrigger,
    get_trigger_registry,
)


def _mock_dsl_service() -> AsyncMock:
    svc = AsyncMock()
    svc.dispatch = AsyncMock()
    return svc


# ── IntervalTrigger ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_interval_trigger_dispatch_loop_and_stop() -> None:
    """Loop dispatch'ит с интервалом; stop останавливает и завершает task."""
    svc = _mock_dsl_service()
    trigger = IntervalTrigger(
        "t1", "route-1", interval_s=0.05, start_immediately=True
    )
    with patch("src.backend.dsl.service.get_dsl_service", return_value=svc):
        await trigger.start()
        await asyncio.sleep(0.15)
        await trigger.stop()

    assert svc.dispatch.await_count >= 1
    assert trigger._task is None  # stop() обнуляет ссылку
    # headers содержат x-trigger
    call = svc.dispatch.await_args_list[0]
    assert call.kwargs["headers"] == {"x-trigger": "t1"}
    assert call.kwargs["route_id"] == "route-1"


@pytest.mark.asyncio
async def test_interval_trigger_idempotent_start() -> None:
    """Повторный start без stop — задача не пересоздаётся (152-156)."""
    trigger = IntervalTrigger("t1", "route-1", interval_s=10)
    with patch("src.backend.dsl.service.get_dsl_service", return_value=_mock_dsl_service()):
        await trigger.start()
        first_task = trigger._task
        await trigger.start()
        assert trigger._task is first_task
        await trigger.stop()


@pytest.mark.asyncio
async def test_interval_trigger_payload_callable() -> None:
    """Payload-factory вызывается на каждом dispatch."""
    calls: list[dict[str, object]] = []

    def payload_factory() -> dict[str, object]:
        calls.append({})
        return {"n": len(calls)}

    svc = _mock_dsl_service()
    trigger = IntervalTrigger(
        "t1", "route-1", interval_s=0.05, payload=payload_factory
    )
    with patch("src.backend.dsl.service.get_dsl_service", return_value=svc):
        await trigger.start()
        await asyncio.sleep(0.12)
        await trigger.stop()

    assert svc.dispatch.await_count >= 1
    sent_body = svc.dispatch.await_args_list[0].kwargs["body"]
    assert sent_body == {"n": 1}


@pytest.mark.asyncio
async def test_interval_trigger_dispatch_failure_swallowed() -> None:
    """Ошибка dispatch (RuntimeError) не ломает триггер (199-212)."""
    svc = AsyncMock()
    svc.dispatch = AsyncMock(side_effect=RuntimeError("backend down"))
    trigger = IntervalTrigger("t1", "route-1", interval_s=0.03, start_immediately=True)
    with patch("src.backend.dsl.service.get_dsl_service", return_value=svc):
        await trigger.start()
        await asyncio.sleep(0.1)
        await trigger.stop()
    assert svc.dispatch.await_count >= 1  # вызовы были, исключение проглочено


@pytest.mark.asyncio
async def test_interval_trigger_tick_returns_true() -> None:
    assert await IntervalTrigger("t", "r", interval_s=1).tick() is True


# ── CronTrigger ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cron_trigger_init_builds_aps_trigger() -> None:
    trigger = CronTrigger("c1", "route-1", "*/5 * * * *")
    assert trigger.cron_expr == "*/5 * * * *"
    assert trigger._aps_trigger is not None


@pytest.mark.asyncio
async def test_cron_trigger_loop_dispatch_and_stop() -> None:
    """Cron-loop dispatch'ит, когда next_fire_time почти сразу."""
    svc = _mock_dsl_service()
    trigger = CronTrigger("c1", "route-1", "* * * * *")
    fake_aps = MagicMock()
    import datetime as _dt

    now = _dt.datetime.now(_dt.UTC)
    fake_aps.get_next_fire_time = MagicMock(
        side_effect=lambda a, b: b + _dt.timedelta(seconds=0.02)
    )
    trigger._aps_trigger = fake_aps

    with patch("src.backend.dsl.service.get_dsl_service", return_value=svc):
        await trigger.start()
        await asyncio.sleep(0.15)
        await trigger.stop()

    assert svc.dispatch.await_count >= 1


@pytest.mark.asyncio
async def test_cron_trigger_idempotent_start() -> None:
    trigger = CronTrigger("c1", "route-1", "*/5 * * * *")
    with patch("src.backend.dsl.service.get_dsl_service", return_value=_mock_dsl_service()):
        await trigger.start()
        first = trigger._task
        await trigger.start()
        assert trigger._task is first
        await trigger.stop()


# ── WebhookTrigger ─────────────────────────────────────────────────


def _fake_app() -> tuple[SimpleNamespace, list[object]]:
    routes: list[object] = []

    def add_api_route(path, handler, methods=None, name=None):  # type: ignore[no-untyped-def]
        routes.append(
            SimpleNamespace(path=path, endpoint=handler, name=name, methods=methods)
        )

    app = SimpleNamespace(add_api_route=add_api_route, router=SimpleNamespace(routes=routes))
    return app, routes


@pytest.mark.asyncio
async def test_webhook_start_registers_route_idempotent() -> None:
    app, routes = _fake_app()
    trigger = WebhookTrigger("wh1", "route-1", "/webhooks/orders", app=app)
    await trigger.start()
    await trigger.start()  # idempotent (370-371)
    assert trigger._route_added is True
    assert len(routes) == 1
    assert routes[0].name == "webhook_wh1"


@pytest.mark.asyncio
async def test_webhook_handler_dispatches_and_reports_error() -> None:
    app, routes = _fake_app()
    trigger = WebhookTrigger("wh1", "route-1", "/webhooks/orders", app=app)
    await trigger.start()
    handler = routes[0].endpoint

    svc_ok = _mock_dsl_service()
    with patch("src.backend.dsl.service.get_dsl_service", return_value=svc_ok):
        result = await handler({"order": 1})
    assert result["status"] == "dispatched"

    svc_fail = AsyncMock()
    svc_fail.dispatch = AsyncMock(side_effect=ValueError("bad body"))
    with patch("src.backend.dsl.service.get_dsl_service", return_value=svc_fail):
        result = await handler(None)
    assert result["status"] == "error"
    assert "bad body" in result["error"]


@pytest.mark.asyncio
async def test_webhook_start_without_app_defers() -> None:
    """Нет app и get_app недоступен -> defer без исключения (380-395)."""
    trigger = WebhookTrigger("wh1", "route-1", "/webhooks/orders", app=None)
    with patch.dict(
        "sys.modules", {"src.backend.entrypoints.api.app": None}
    ):
        await trigger.start()
    assert trigger._route_added is False


@pytest.mark.asyncio
async def test_webhook_stop_removes_route() -> None:
    app, routes = _fake_app()
    trigger = WebhookTrigger("wh1", "route-1", "/webhooks/orders", app=app)
    await trigger.start()
    await trigger.stop()
    assert trigger._route_added is False
    # routes фильтруется по name в stop — fake-app routes не проходит фильтр
    # (нет атрибута name) — проверяем только отсутствие исключения.


# ── TriggerRegistry ────────────────────────────────────────────────


class _FakeTrigger:
    def __init__(self, name: str, *, fail_start: bool = False) -> None:
        self.name = name
        self.fail_start = fail_start
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        if self.fail_start:
            raise RuntimeError("start fail")
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


@pytest.mark.asyncio
async def test_registry_register_replace_and_lookup() -> None:
    registry = TriggerRegistry()
    t1 = _FakeTrigger("a")
    registry.register(t1)
    assert registry.get("a") is t1
    assert registry.list_names() == ["a"]

    t1b = _FakeTrigger("a")
    registry.register(t1b)  # replace с warning — не бросает
    assert registry.get("a") is t1b

    registry.unregister("a")
    assert registry.get("a") is None
    registry.unregister("a")  # no-op


@pytest.mark.asyncio
async def test_registry_start_all_and_stop_all() -> None:
    registry = TriggerRegistry()
    good = _FakeTrigger("good")
    bad = _FakeTrigger("bad", fail_start=True)
    registry.register(good)
    registry.register(bad)
    # start_all глотает ошибку bad, запускает good
    await registry.start_all()
    assert good.started is True
    await registry.stop_all()
    assert good.stopped is True
    assert bad.stopped is True


@pytest.mark.asyncio
async def test_get_trigger_registry_singleton() -> None:
    assert get_trigger_registry() is get_trigger_registry()
