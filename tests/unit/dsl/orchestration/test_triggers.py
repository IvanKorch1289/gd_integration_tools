"""Unit tests для Route Triggers (S55 W4).

Camel-style ``from(...)`` builders: from_interval, from_webhook, TriggerRegistry.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.orchestration.triggers import (
    IntervalTrigger,
    TriggerRegistry,
    WebhookTrigger,
    get_trigger_registry,
)

# ── IntervalTrigger ────────────────────────────────────────────────


class TestIntervalTrigger:
    @pytest.mark.asyncio
    async def test_fires_after_interval(self) -> None:
        trigger = IntervalTrigger(
            name="test_interval", route_id="test_route", interval_s=0.1
        )
        with patch("src.backend.dsl.service.get_dsl_service") as mock_get_svc:
            mock_svc = MagicMock()
            mock_svc.dispatch = AsyncMock()
            mock_get_svc.return_value = mock_svc

            await trigger.start()
            await asyncio.sleep(0.25)  # 2+ intervals
            await trigger.stop()

        # Should have dispatched at least 2 times
        assert mock_svc.dispatch.call_count >= 2
        # Last call should have correct route_id + trigger header
        call = mock_svc.dispatch.call_args_list[-1]
        assert call.kwargs["route_id"] == "test_route"
        assert call.kwargs["headers"]["x-trigger"] == "test_interval"

    @pytest.mark.asyncio
    async def test_start_immediately(self) -> None:
        trigger = IntervalTrigger(
            name="immediate",
            route_id="r1",
            interval_s=10.0,
            start_immediately=True,
            payload={"x": 1},
        )
        with patch("src.backend.dsl.service.get_dsl_service") as mock_get_svc:
            mock_svc = MagicMock()
            mock_svc.dispatch = AsyncMock()
            mock_get_svc.return_value = mock_svc

            await trigger.start()
            await asyncio.sleep(0.1)
            await trigger.stop()

        # First dispatch happened immediately
        first_call = mock_svc.dispatch.call_args_list[0]
        assert first_call.kwargs["body"] == {"x": 1}

    @pytest.mark.asyncio
    async def test_payload_factory(self) -> None:
        counter = {"n": 0}

        def factory() -> dict[str, Any]:
            counter["n"] += 1
            return {"count": counter["n"]}

        trigger = IntervalTrigger(
            name="factory",
            route_id="r1",
            interval_s=0.05,
            start_immediately=True,
            payload=factory,
        )
        with patch("src.backend.dsl.service.get_dsl_service") as mock_get_svc:
            mock_svc = MagicMock()
            mock_svc.dispatch = AsyncMock()
            mock_get_svc.return_value = mock_svc

            await trigger.start()
            await asyncio.sleep(0.15)
            await trigger.stop()

        # 3+ invocations, each with increasing count
        assert mock_svc.dispatch.call_count >= 3
        bodies = [c.kwargs["body"]["count"] for c in mock_svc.dispatch.call_args_list]
        assert bodies == sorted(set(bodies))  # strictly increasing

    @pytest.mark.asyncio
    async def test_dispatch_exception_logged_not_raised(self) -> None:
        trigger = IntervalTrigger(
            name="fail", route_id="r1", interval_s=0.05, start_immediately=True
        )
        with patch("src.backend.dsl.service.get_dsl_service") as mock_get_svc:
            mock_svc = MagicMock()
            mock_svc.dispatch = AsyncMock(side_effect=RuntimeError("boom"))
            mock_get_svc.return_value = mock_svc

            await trigger.start()
            await asyncio.sleep(0.15)
            await trigger.stop()  # should not raise


# ── TriggerRegistry ────────────────────────────────────────────────


class TestTriggerRegistry:
    def test_register_and_get(self) -> None:
        reg = TriggerRegistry()
        t = IntervalTrigger(name="t1", route_id="r1", interval_s=1.0)
        reg.register(t)
        assert reg.get("t1") is t

    def test_register_replaces(self) -> None:
        reg = TriggerRegistry()
        t1 = IntervalTrigger(name="t1", route_id="r1", interval_s=1.0)
        t2 = IntervalTrigger(name="t1", route_id="r2", interval_s=2.0)
        reg.register(t1)
        reg.register(t2)
        assert reg.get("t1") is t2

    def test_unregister(self) -> None:
        reg = TriggerRegistry()
        t = IntervalTrigger(name="t1", route_id="r1", interval_s=1.0)
        reg.register(t)
        reg.unregister("t1")
        assert reg.get("t1") is None

    def test_list_names(self) -> None:
        reg = TriggerRegistry()
        reg.register(IntervalTrigger(name="a", route_id="r1", interval_s=1.0))
        reg.register(IntervalTrigger(name="b", route_id="r2", interval_s=1.0))
        assert set(reg.list_names()) == {"a", "b"}

    @pytest.mark.asyncio
    async def test_start_all_starts_all(self) -> None:
        reg = TriggerRegistry()
        a = MagicMock()
        a.name = "a"
        a.start = AsyncMock()
        b = MagicMock()
        b.name = "b"
        b.start = AsyncMock()
        reg.register(a)  # type: ignore[arg-type]
        reg.register(b)  # type: ignore[arg-type]
        await reg.start_all()
        a.start.assert_awaited_once()
        b.start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_all_stops_all(self) -> None:
        reg = TriggerRegistry()
        a = MagicMock()
        a.name = "a"
        a.stop = AsyncMock()
        b = MagicMock()
        b.name = "b"
        b.stop = AsyncMock()
        reg.register(a)  # type: ignore[arg-type]
        reg.register(b)  # type: ignore[arg-type]
        await reg.stop_all()
        a.stop.assert_awaited_once()
        b.stop.assert_awaited_once()


# ── WebhookTrigger ─────────────────────────────────────────────────


class TestWebhookTrigger:
    @pytest.mark.asyncio
    async def test_registers_route_on_app(self) -> None:
        from fastapi import FastAPI

        app = FastAPI()
        trigger = WebhookTrigger(
            name="orders_hook",
            route_id="orders_route",
            path="/webhooks/orders",
            method="POST",
            app=app,
        )
        await trigger.start()
        # Verify route was added
        paths = [r.path for r in app.router.routes if hasattr(r, "path")]
        assert "/webhooks/orders" in paths

    @pytest.mark.asyncio
    async def test_dispatches_on_call(self) -> None:
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        app = FastAPI()
        with patch("src.backend.dsl.service.get_dsl_service") as mock_get_svc:
            mock_svc = MagicMock()
            mock_svc.dispatch = AsyncMock()
            mock_get_svc.return_value = mock_svc

            trigger = WebhookTrigger(
                name="orders_hook",
                route_id="orders_route",
                path="/webhooks/orders",
                app=app,
            )
            await trigger.start()

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/webhooks/orders", json={"order_id": 123})
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "dispatched"
            assert data["route_id"] == "orders_route"

            # Verify dsl.dispatch was called
            mock_svc.dispatch.assert_awaited_once()
            call = mock_svc.dispatch.call_args
            assert call.kwargs["body"] == {"order_id": 123}
            assert call.kwargs["headers"]["x-webhook"] == "orders_hook"


# ── Singleton accessor ───────────────────────────────────────────


def test_singleton_accessor() -> None:
    reg1 = get_trigger_registry()
    reg2 = get_trigger_registry()
    assert reg1 is reg2
