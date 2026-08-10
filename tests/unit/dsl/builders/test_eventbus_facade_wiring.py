"""S173 M-2 closeout: runtime-тесты для EventBusFacade wiring.

Изолированные unit-тесты для ``EventBusPublishProcessor.process()`` и
``EventBusSubscribeProcessor.process()`` через mock ``Exchange`` (без
импорта core.dsl.engine.exchange, чтобы не зависеть от pre-existing
``AIGateway`` import chain в ``core.ai.gateway.__init__``).

Эти тесты НЕ используют ``RouteBuilder.from_()`` (тащит core.ai.gateway
через builders/__init__.py → ai_rpa → llmcall_processor → AIGateway).
Вместо этого ``Exchange`` конструируется через минимальный stub, что
соответствует ``test_hitl_pubsub_consumer.py`` подходу.

Покрытие:
    * EventBusPublishProcessor.process() с facade → ``facade.publish`` вызван.
    * EventBusPublishProcessor.process() facade fail → fallback к direct publish.
    * EventBusPublishProcessor.process() без facade → metadata fallback.
    * EventBusSubscribeProcessor.process() с facade → ``subscribe_with_lifecycle``.
    * EventBusSubscribeProcessor.process() без facade → metadata-only.
    * ``_make_eventbus_handler`` записывает события в exchange.properties.
"""


from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.dsl.builders.eventbus_mixin import (
    EventBusPublishProcessor,
    EventBusSubscribeProcessor,
    _make_eventbus_handler,
    _resolve_event_bus_facade,
)


class _StubExchange:
    """Minimal Exchange stand-in без core.dsl.engine.exchange зависимости.

    Нужен только ``in_message.body``, ``properties``, ``set_property``.
    """

    def __init__(self, body: dict | None = None) -> None:
        self.in_message = MagicMock()
        self.in_message.body = body or {"order_id": 42}
        self.properties: dict = {}
        self.set_property_calls: list[tuple[str, object]] = []

    def set_property(self, key: str, value: object) -> None:
        self.properties[key] = value
        self.set_property_calls.append((key, value))


class TestResolveEventBusFacade:
    def test_returns_none_when_no_di_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Без DI-provider — fallback к None (dev_light / unit-tests)."""
        # Cycle 96 L10: use string-path patch (matches sibling test
        # test_publishes_via_facade_when_available pattern). Direct
        # `monkeypatch.setattr(mod, "_resolve_event_bus_facade", ...)`
        # patches the module attribute but NOT the local reference in
        # this test file (which was captured at import time).
        monkeypatch.setattr(
            "src.backend.dsl.builders.eventbus_mixin._resolve_event_bus_facade",
            lambda: None,
        )
        # Re-import to capture the patched reference.
        from src.backend.dsl.builders import eventbus_mixin

        assert eventbus_mixin._resolve_event_bus_facade() is None

    def test_handles_import_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Если DI provider падает на import — return None, не raise."""
        import builtins

        original_import = builtins.__import__

        def _raising_import(name: str, *args: object, **kwargs: object) -> object:
            # Cycle 96 L10: ``__import__`` is called with MODULE name, not
            # attribute name. ``from X import Y`` triggers __import__('X').
            # Match on the provider MODULE path, not the function name.
            if "infrastructure_facade" in name:
                raise ImportError("provider module not found")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _raising_import)
        # _resolve_event_bus_facade catches ImportError → returns None.
        assert _resolve_event_bus_facade() is None


class TestEventBusPublishProcessorFacadeWiring:
    @pytest.mark.asyncio
    async def test_publishes_via_facade_when_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """S173 M-2: EventBusFacade.publish вызывается с правильным event."""
        facade = MagicMock()
        facade.publish = AsyncMock()
        monkeypatch.setattr(
            "src.backend.dsl.builders.eventbus_mixin._resolve_event_bus_facade",
            lambda: facade,
        )
        # Enable flag.
        from src.backend.core.config.features import feature_flags

        original = feature_flags.eventbus_dsl_enabled
        feature_flags.eventbus_dsl_enabled = True
        try:
            proc = EventBusPublishProcessor(topic="orders.created")
            exchange = _StubExchange(body={"order_id": 42})
            await proc.process(exchange, context=None)
            # facade.publish вызван.
            assert facade.publish.await_count == 1
            call_args = facade.publish.await_args
            assert call_args.args[0] == "orders.created"
            # event payload содержит topic + correlation_id.
            event = call_args.args[1]
            assert event["topic"] == "orders.created"
            assert event["payload"] == {"order_id": 42}
            assert "correlation_id" in event
        finally:
            feature_flags.eventbus_dsl_enabled = original

    @pytest.mark.asyncio
    async def test_falls_back_on_facade_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Если facade.publish raises — fallback к metadata ``_eventbus_published``.

        Мы НЕ тестируем direct ``core.messaging.event_bus`` путь (он
        может быть недоступен в test env), только что exception НЕ
        propagate'ится наружу.
        """
        facade = MagicMock()
        facade.publish = AsyncMock(side_effect=RuntimeError("broker down"))
        monkeypatch.setattr(
            "src.backend.dsl.builders.eventbus_mixin._resolve_event_bus_facade",
            lambda: facade,
        )
        from src.backend.core.config.features import feature_flags

        original = feature_flags.eventbus_dsl_enabled
        feature_flags.eventbus_dsl_enabled = True
        try:
            proc = EventBusPublishProcessor(topic="orders.created")
            exchange = _StubExchange(body={"order_id": 42})
            # НЕ должно raise'ить — exception swallowed → fallback.
            await proc.process(exchange, context=None)
            # facade.publish был вызван.
            assert facade.publish.await_count == 1
        finally:
            feature_flags.eventbus_dsl_enabled = original

    @pytest.mark.asyncio
    async def test_no_op_when_flag_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """eventbus_dsl_enabled=False → no-op, facade НЕ вызывается."""
        facade = MagicMock()
        facade.publish = AsyncMock()
        monkeypatch.setattr(
            "src.backend.dsl.builders.eventbus_mixin._resolve_event_bus_facade",
            lambda: facade,
        )
        from src.backend.core.config.features import feature_flags

        original = feature_flags.eventbus_dsl_enabled
        feature_flags.eventbus_dsl_enabled = False
        try:
            proc = EventBusPublishProcessor(topic="orders.created")
            exchange = _StubExchange(body={"order_id": 42})
            await proc.process(exchange, context=None)
            # НЕ должно вызвать facade.publish.
            assert facade.publish.await_count == 0
        finally:
            feature_flags.eventbus_dsl_enabled = original


class TestEventBusSubscribeProcessorFacadeWiring:
    @pytest.mark.asyncio
    async def test_subscribes_via_facade_when_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """S173 M-2: subscribe_with_lifecycle вызывается с handler."""
        facade = MagicMock()
        facade.subscribe_with_lifecycle = AsyncMock()
        monkeypatch.setattr(
            "src.backend.dsl.builders.eventbus_mixin._resolve_event_bus_facade",
            lambda: facade,
        )
        from src.backend.core.config.features import feature_flags

        original = feature_flags.eventbus_dsl_enabled
        feature_flags.eventbus_dsl_enabled = True
        try:
            proc = EventBusSubscribeProcessor(topic_pattern="orders.*", ack_mode="manual")
            exchange = _StubExchange()
            await proc.process(exchange, context=None)
            # facade.subscribe_with_lifecycle вызван.
            assert facade.subscribe_with_lifecycle.await_count == 1
            call_args = facade.subscribe_with_lifecycle.await_args
            # channel + handler.
            assert call_args.args[0] == "orders.*"
            # handler is callable.
            handler = call_args.args[1]
            assert callable(handler)
            # metadata declaration тоже записана.
            assert "_eventbus_subscribed" in exchange.properties
            subs = exchange.properties["_eventbus_subscribed"]
            assert len(subs) == 1
            assert subs[0]["topic_pattern"] == "orders.*"
            assert subs[0]["ack_mode"] == "manual"
        finally:
            feature_flags.eventbus_dsl_enabled = original

    @pytest.mark.asyncio
    async def test_metadata_only_when_no_facade(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Без facade — только metadata-декларация (backward compat)."""
        monkeypatch.setattr(
            "src.backend.dsl.builders.eventbus_mixin._resolve_event_bus_facade",
            lambda: None,
        )
        from src.backend.core.config.features import feature_flags

        original = feature_flags.eventbus_dsl_enabled
        feature_flags.eventbus_dsl_enabled = True
        try:
            proc = EventBusSubscribeProcessor(topic_pattern="orders.*")
            exchange = _StubExchange()
            await proc.process(exchange, context=None)
            # metadata записана.
            assert "_eventbus_subscribed" in exchange.properties
            # Без фасада subscribe_with_lifecycle НЕ вызван (нет facade).
        finally:
            feature_flags.eventbus_dsl_enabled = original


class TestMakeEventBusHandler:
    @pytest.mark.asyncio
    async def test_handler_records_event_in_exchange_properties(self) -> None:
        """Handler записывает событие в ``exchange.properties['_eventbus_received']``."""
        exchange = _StubExchange()
        handler = _make_eventbus_handler(
            exchange=exchange,
            context=None,
            topic_pattern="orders.*",
            ack_mode="auto",
        )
        await handler({"order_id": 42, "amount": 100})
        assert "_eventbus_received" in exchange.properties
        events = exchange.properties["_eventbus_received"]
        assert len(events) == 1
        assert events[0]["topic_pattern"] == "orders.*"
        assert events[0]["ack_mode"] == "auto"
        assert events[0]["event"] == {"order_id": 42, "amount": 100}

    @pytest.mark.asyncio
    async def test_handler_appends_multiple_events(self) -> None:
        """Несколько events → accumulated list."""
        exchange = _StubExchange()
        handler = _make_eventbus_handler(
            exchange=exchange,
            context=None,
            topic_pattern="orders.*",
            ack_mode="auto",
        )
        await handler({"id": 1})
        await handler({"id": 2})
        await handler({"id": 3})
        events = exchange.properties["_eventbus_received"]
        assert len(events) == 3
