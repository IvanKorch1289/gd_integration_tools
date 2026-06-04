"""Unit-тесты routing processors: DynamicRouter, ScatterGather, RecipientList,
LoadBalancer, Multicast, MulticastRoutes.

Паттерн: async tests, _ex fixture, моки для RouteRegistry / SubPipelineExecutor.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.eip.routing import (
    DynamicRouterProcessor,
    LoadBalancerProcessor,
    MulticastProcessor,
    MulticastRoutesProcessor,
    RecipientListProcessor,
    ScatterGatherProcessor,
)


def _ex(body: Any = None, headers: dict[str, Any] | None = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers=headers or {}))


class DummyProcessor(BaseProcessor):
    """Процессор, который выставляет out_message.body = payload."""

    def __init__(self, payload: Any, name: str | None = None) -> None:
        super().__init__(name=name or "dummy")
        self._payload = payload

    async def process(self, exchange: Exchange[Any], context: Any) -> None:
        exchange.out_message = Message(body=self._payload)


class FailingProcessor(BaseProcessor):
    """Процессор, который падает с RuntimeError."""

    async def process(self, exchange: Exchange[Any], context: Any) -> None:
        raise RuntimeError("branch fail")


# =============================================================================
# DynamicRouterProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_dynamic_router_unregistered_route_fails() -> None:
    """Незарегистрированный route → exchange.fail."""
    proc = DynamicRouterProcessor(route_expression=lambda ex: "unknown_route")
    ctx = AsyncMock()
    e = _ex(body={"id": 1})

    with patch("src.backend.dsl.commands.registry.route_registry") as mock_reg:
        mock_reg.is_registered.return_value = False
        await proc.process(e, ctx)

    assert e.status == ExchangeStatus.failed
    assert "unknown_route" in (e.error or "")


@pytest.mark.asyncio
async def test_dynamic_router_success() -> None:
    """Зарегистрированный route → результат в out_message."""
    proc = DynamicRouterProcessor(route_expression=lambda ex: "target_route")
    ctx = AsyncMock()
    e = _ex(body={"id": 1})

    with patch("src.backend.dsl.commands.registry.route_registry") as mock_reg:
        mock_reg.is_registered.return_value = True
        with patch(
            "src.backend.dsl.engine.processors.base.SubPipelineExecutor.execute_route",
            new_callable=AsyncMock,
        ) as mock_exec:
            mock_exec.return_value = ({"routed": True}, None)
            await proc.process(e, ctx)

    assert e.properties.get("dynamic_route_used") == "target_route"
    assert e.out_message.body == {"routed": True}


@pytest.mark.asyncio
async def test_dynamic_router_subpipeline_error() -> None:
    """Ошибка в sub-pipeline → exchange.fail."""
    proc = DynamicRouterProcessor(route_expression=lambda ex: "bad_route")
    ctx = AsyncMock()
    e = _ex(body={"id": 1})

    with patch("src.backend.dsl.commands.registry.route_registry") as mock_reg:
        mock_reg.is_registered.return_value = True
        with patch(
            "src.backend.dsl.engine.processors.base.SubPipelineExecutor.execute_route",
            new_callable=AsyncMock,
        ) as mock_exec:
            mock_exec.return_value = (None, "sub-error")
            await proc.process(e, ctx)

    assert e.status == ExchangeStatus.failed
    assert "sub-error" in (e.error or "")


# =============================================================================
# ScatterGatherProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_scatter_gather_success_merge() -> None:
    """Успешное выполнение нескольких route → merge результатов."""
    proc = ScatterGatherProcessor(route_ids=["a", "b"], aggregation="merge")
    ctx = AsyncMock()
    e = _ex(body={"input": 1})

    with patch(
        "src.backend.dsl.engine.processors.base.SubPipelineExecutor.execute_route_safe",
        new_callable=AsyncMock,
    ) as mock_exec:
        mock_exec.side_effect = [("a", {"x": 1}, None), ("b", {"y": 2}, None)]
        await proc.process(e, ctx)

    assert e.properties.get("scatter_results") == {"a": {"x": 1}, "b": {"y": 2}}
    assert e.out_message.body == {"x": 1, "y": 2}


@pytest.mark.asyncio
async def test_scatter_gather_timeout() -> None:
    """Таймаут scatter-gather → exchange.fail."""
    proc = ScatterGatherProcessor(
        route_ids=["slow"], timeout_seconds=0.01, aggregation="list"
    )
    ctx = AsyncMock()
    e = _ex(body={"input": 1})

    with patch(
        "src.backend.dsl.engine.processors.base.SubPipelineExecutor.execute_route_safe",
        new_callable=AsyncMock,
    ) as mock_exec:
        mock_exec.side_effect = lambda *a, **k: AsyncMock()
        # simulate actual sleep inside coroutine
        import asyncio

        async def slow(*a, **k):
            await asyncio.sleep(1)
            return ("slow", None, None)

        mock_exec.side_effect = slow
        await proc.process(e, ctx)

    assert e.status == ExchangeStatus.failed
    assert "timeout" in (e.error or "").lower()


@pytest.mark.asyncio
async def test_scatter_gather_errors_collected() -> None:
    """Ошибки собираются в scatter_errors, out_message не выставляется."""
    proc = ScatterGatherProcessor(route_ids=["ok", "err"], aggregation="merge")
    ctx = AsyncMock()
    e = _ex(body={"input": 1})

    with patch(
        "src.backend.dsl.engine.processors.base.SubPipelineExecutor.execute_route_safe",
        new_callable=AsyncMock,
    ) as mock_exec:
        mock_exec.side_effect = [("ok", {"v": 1}, None), ("err", None, "boom")]
        await proc.process(e, ctx)

    assert e.properties.get("scatter_errors") == {"err": "boom"}
    assert e.out_message.body == {"v": 1}


# =============================================================================
# RecipientListProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_recipient_list_parallel() -> None:
    """Параллельная отправка на несколько маршрутов."""
    proc = RecipientListProcessor(
        recipients_expression=lambda ex: ["r1", "r2"], parallel=True
    )
    ctx = AsyncMock()
    e = _ex(body={"input": 1})

    with patch(
        "src.backend.dsl.engine.processors.base.SubPipelineExecutor.execute_route_safe",
        new_callable=AsyncMock,
    ) as mock_exec:
        mock_exec.side_effect = [("r1", {"v": 1}, None), ("r2", {"v": 2}, None)]
        await proc.process(e, ctx)

    assert e.properties.get("recipient_results") == {"r1": {"v": 1}, "r2": {"v": 2}}


@pytest.mark.asyncio
async def test_recipient_list_sequential() -> None:
    """Последовательная отправка на несколько маршрутов."""
    call_order: list[str] = []

    async def side_effect(route_id, body, headers, context):
        call_order.append(route_id)
        return (route_id, {"v": route_id}, None)

    proc = RecipientListProcessor(
        recipients_expression=lambda ex: ["r1", "r2"], parallel=False
    )
    ctx = AsyncMock()
    e = _ex(body={"input": 1})

    with patch(
        "src.backend.dsl.engine.processors.base.SubPipelineExecutor.execute_route_safe",
        new_callable=AsyncMock,
    ) as mock_exec:
        mock_exec.side_effect = side_effect
        await proc.process(e, ctx)

    assert call_order == ["r1", "r2"]
    assert e.properties.get("recipient_results") == {
        "r1": {"v": "r1"},
        "r2": {"v": "r2"},
    }


@pytest.mark.asyncio
async def test_recipient_list_empty() -> None:
    """Пустой список recipients → ничего не делается."""
    proc = RecipientListProcessor(recipients_expression=lambda ex: [])
    ctx = AsyncMock()
    e = _ex(body={"input": 1})
    await proc.process(e, ctx)

    assert "recipient_results" not in e.properties


# =============================================================================
# LoadBalancerProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_load_balancer_round_robin() -> None:
    """Round-robin циклически перебирает targets."""
    proc = LoadBalancerProcessor(targets=["a", "b", "c"], strategy="round_robin")
    ctx = AsyncMock()

    targets_hit: list[str] = []

    with patch(
        "src.backend.dsl.engine.processors.base.SubPipelineExecutor.execute_route",
        new_callable=AsyncMock,
    ) as mock_exec:

        async def track(target, body, headers, context):
            targets_hit.append(target)
            return ({"target": target}, None)

        mock_exec.side_effect = track

        for _ in range(4):
            e = _ex(body={"i": _})
            await proc.process(e, ctx)

    assert targets_hit == ["a", "b", "c", "a"]


@pytest.mark.asyncio
async def test_load_balancer_random() -> None:
    """Random strategy выбивает один из targets."""
    proc = LoadBalancerProcessor(targets=["a", "b"], strategy="random")
    ctx = AsyncMock()
    e = _ex(body={"input": 1})

    with patch(
        "src.backend.dsl.engine.processors.base.SubPipelineExecutor.execute_route",
        new_callable=AsyncMock,
    ) as mock_exec:
        mock_exec.return_value = ({"ok": True}, None)
        await proc.process(e, ctx)

    assert mock_exec.awaited
    assert e.properties.get("lb_target") in ("a", "b")


@pytest.mark.asyncio
async def test_load_balancer_weighted() -> None:
    """Weighted strategy использует weights."""
    proc = LoadBalancerProcessor(
        targets=["a", "b"], strategy="weighted", weights=[1, 0]
    )
    ctx = AsyncMock()

    with patch(
        "src.backend.dsl.engine.processors.base.SubPipelineExecutor.execute_route",
        new_callable=AsyncMock,
    ) as mock_exec:
        mock_exec.return_value = ({"ok": True}, None)
        for _ in range(5):
            e = _ex(body={"i": _})
            await proc.process(e, ctx)

    # weight=[1,0] → всегда выбирается "a"
    for call in mock_exec.await_args_list:
        assert call[0][0] == "a"


@pytest.mark.asyncio
async def test_load_balancer_sticky() -> None:
    """Sticky strategy привязывает к header."""
    proc = LoadBalancerProcessor(
        targets=["a", "b"], strategy="sticky", sticky_header="user-id"
    )
    ctx = AsyncMock()

    with patch(
        "src.backend.dsl.engine.processors.base.SubPipelineExecutor.execute_route",
        new_callable=AsyncMock,
    ) as mock_exec:
        mock_exec.return_value = ({"ok": True}, None)
        e1 = _ex(body={}, headers={"user-id": "u1"})
        await proc.process(e1, ctx)
        target1 = e1.properties.get("lb_target")

        e2 = _ex(body={}, headers={"user-id": "u1"})
        await proc.process(e2, ctx)
        target2 = e2.properties.get("lb_target")

    assert target1 == target2


@pytest.mark.asyncio
async def test_load_balancer_fallback_to_first() -> None:
    """Неизвестная strategy → первый target."""
    proc = LoadBalancerProcessor(targets=["x", "y"], strategy="unknown")
    ctx = AsyncMock()
    e = _ex(body={})

    with patch(
        "src.backend.dsl.engine.processors.base.SubPipelineExecutor.execute_route",
        new_callable=AsyncMock,
    ) as mock_exec:
        mock_exec.return_value = ({"ok": True}, None)
        await proc.process(e, ctx)

    assert e.properties.get("lb_target") == "x"


@pytest.mark.asyncio
async def test_load_balancer_target_failure() -> None:
    """Ошибка target → exchange.fail."""
    proc = LoadBalancerProcessor(targets=["a"], strategy="round_robin")
    ctx = AsyncMock()
    e = _ex(body={})

    with patch(
        "src.backend.dsl.engine.processors.base.SubPipelineExecutor.execute_route",
        new_callable=AsyncMock,
    ) as mock_exec:
        mock_exec.return_value = (None, "conn refused")
        await proc.process(e, ctx)

    assert e.status == ExchangeStatus.failed
    assert "conn refused" in (e.error or "")


# =============================================================================
# MulticastProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_multicast_all_strategy() -> None:
    """Multicast all → собирает результаты всех веток."""
    proc = MulticastProcessor(
        branches=[[DummyProcessor({"a": 1})], [DummyProcessor({"b": 2})]],
        strategy="all",
    )
    ctx = AsyncMock()
    e = _ex(body={"input": 1})

    await proc.process(e, ctx)

    assert e.properties.get("multicast_results") == [{"a": 1}, {"b": 2}]


@pytest.mark.asyncio
async def test_multicast_first_strategy() -> None:
    """Multicast first → первый завершённый результат."""
    import asyncio

    async def slow(ex: Exchange[Any], ctx: Any) -> None:
        await asyncio.sleep(0.1)
        ex.out_message = Message(body={"slow": True})

    proc = MulticastProcessor(
        branches=[[DummyProcessor({"fast": True})], [slow]], strategy="first"
    )
    ctx = AsyncMock()
    e = _ex(body={"input": 1})

    await proc.process(e, ctx)

    results = e.properties.get("multicast_results", [])
    assert results[0] == {"fast": True}


@pytest.mark.asyncio
async def test_multicast_stop_on_error() -> None:
    """Ошибка в ветке записывается в multicast_errors."""
    proc = MulticastProcessor(
        branches=[[DummyProcessor({"ok": True})], [FailingProcessor()]],
        strategy="all",
        stop_on_error=False,
    )
    ctx = AsyncMock()
    e = _ex(body={"input": 1})

    await proc.process(e, ctx)

    errors = e.properties.get("multicast_errors", {})
    assert 1 in errors
    assert "branch fail" in errors[1]


# =============================================================================
# MulticastRoutesProcessor
# =============================================================================


def test_multicast_routes_invalid_strategy() -> None:
    """Неверный strategy → ValueError при инициализации."""
    with pytest.raises(ValueError, match="strategy"):
        MulticastRoutesProcessor(route_ids=["a"], strategy="invalid")


def test_multicast_routes_invalid_on_error() -> None:
    """Неверный on_error → ValueError при инициализации."""
    with pytest.raises(ValueError, match="on_error"):
        MulticastRoutesProcessor(route_ids=["a"], on_error="invalid")


@pytest.mark.asyncio
async def test_multicast_routes_all_success() -> None:
    """all strategy → все результаты собраны."""
    proc = MulticastRoutesProcessor(route_ids=["a", "b"], strategy="all")
    ctx = AsyncMock()
    e = _ex(body={"input": 1})

    mock_pipeline = MagicMock()
    mock_registry = MagicMock()
    mock_registry.get_optional.return_value = mock_pipeline

    with patch("src.backend.dsl.commands.registry.route_registry", mock_registry):
        with patch(
            "src.backend.dsl.engine.execution_engine.ExecutionEngine"
        ) as mock_engine_cls:
            mock_engine = MagicMock()
            mock_engine_cls.return_value = mock_engine

            async def fake_execute(pipeline, exchange, context):
                exchange.out_message = Message(body={"result": pipeline})

            mock_engine.execute = fake_execute
            await proc.process(e, ctx)

    results = e.properties.get("multicast_route_results", {})
    assert "a" in results
    assert "b" in results


@pytest.mark.asyncio
async def test_multicast_routes_first_success() -> None:
    """first_success → только первый успешный результат."""
    proc = MulticastRoutesProcessor(route_ids=["a", "b"], strategy="first_success")
    ctx = AsyncMock()
    e = _ex(body={"input": 1})

    mock_registry = MagicMock()
    mock_registry.get_optional.return_value = MagicMock()

    with patch("src.backend.dsl.commands.registry.route_registry", mock_registry):
        with patch(
            "src.backend.dsl.engine.execution_engine.ExecutionEngine"
        ) as mock_engine_cls:
            mock_engine = MagicMock()
            mock_engine_cls.return_value = mock_engine

            async def fake_execute(pipeline, exchange, context):
                exchange.out_message = Message(body={"result": "first"})

            mock_engine.execute = fake_execute
            await proc.process(e, ctx)

    results = e.properties.get("multicast_route_results", {})
    assert len(results) == 1


@pytest.mark.asyncio
async def test_multicast_routes_on_error_fail() -> None:
    """on_error=fail → при ошибке exchange.fail."""
    proc = MulticastRoutesProcessor(route_ids=["a"], strategy="all", on_error="fail")
    ctx = AsyncMock()
    e = _ex(body={"input": 1})

    mock_registry = MagicMock()
    mock_registry.get_optional.return_value = MagicMock()

    with patch("src.backend.dsl.commands.registry.route_registry", mock_registry):
        with patch(
            "src.backend.dsl.engine.execution_engine.ExecutionEngine"
        ) as mock_engine_cls:
            mock_engine = MagicMock()
            mock_engine_cls.return_value = mock_engine

            async def fake_execute(pipeline, exchange, context):
                exchange.fail("route error")

            mock_engine.execute = fake_execute
            await proc.process(e, ctx)

    assert e.status == ExchangeStatus.failed
    assert "route error" in (e.error or "")


@pytest.mark.asyncio
async def test_multicast_routes_unregistered_route() -> None:
    """Незарегистрированный route → ошибка в results."""
    proc = MulticastRoutesProcessor(route_ids=["missing"], strategy="all")
    ctx = AsyncMock()
    e = _ex(body={"input": 1})

    mock_registry = MagicMock()
    mock_registry.get_optional.return_value = None

    with patch("src.backend.dsl.commands.registry.route_registry", mock_registry):
        with patch(
            "src.backend.dsl.engine.execution_engine.ExecutionEngine"
        ) as mock_engine_cls:
            mock_engine_cls.return_value = MagicMock()
            await proc.process(e, ctx)

    errors = e.properties.get("multicast_route_errors", {})
    assert "missing" in errors


def test_multicast_routes_to_spec() -> None:
    """to_spec возвращает корректный dict."""
    proc = MulticastRoutesProcessor(
        route_ids=["a", "b"], strategy="first_success", on_error="fail", timeout=5.0
    )
    spec = proc.to_spec()
    assert spec == {
        "multicast_routes": {
            "route_ids": ["a", "b"],
            "strategy": "first_success",
            "on_error": "fail",
            "timeout": 5.0,
        }
    }
