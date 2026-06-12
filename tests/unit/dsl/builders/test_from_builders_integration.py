"""S98 W3 — DSL integration tests для 12+ from_* builders.

Pre-S98: ``RouteBuilder`` had ``__slots__=()`` без ``__init__``, builders
ломались. Post-S97 W1 fix builders work, но **НЕ** integration-tested.

S98 W3: тесты для топ-5 builders (from_cdc, from_kafka, from_rabbit,
from_file, from_webhook) + comprehensive chainable test — реальный DSL
integration через RouteBuilder (НЕ _FakeRouteBuilder).
"""
from __future__ import annotations


def test_route_builder_from_cdc() -> None:
    """``RouteBuilder.from_cdc`` создаёт builder + cdc source."""
    from src.backend.dsl.builders.base import RouteBuilder

    b = RouteBuilder.from_cdc(
        "orders.stream", table="orders", dsn="postgresql://localhost/db"
    )
    assert b.route_id == "orders.stream"
    assert "orders" in b.source.lower() or "cdc" in b.source.lower()


def test_route_builder_from_kafka() -> None:
    """``RouteBuilder.from_kafka`` создаёт builder + kafka source."""
    from src.backend.dsl.builders.base import RouteBuilder

    b = RouteBuilder.from_kafka(
        "events.stream",
        topic="user.events",
        bootstrap_servers="kafka:9092",
        group_id="consumer_group_1",
    )
    assert b.route_id == "events.stream"
    assert "kafka" in b.source.lower() or "user.events" in b.source.lower()


def test_route_builder_from_rabbit() -> None:
    """``RouteBuilder.from_rabbit`` создаёт builder + rabbit source."""
    from src.backend.dsl.builders.base import RouteBuilder

    b = RouteBuilder.from_rabbit(
        "jobs.queue", queue="jobs", url="amqp://rabbit:5672"
    )
    assert b.route_id == "jobs.queue"


def test_route_builder_from_filewatcher() -> None:
    """``RouteBuilder.from_filewatcher`` создаёт builder + file source."""
    from src.backend.dsl.builders.base import RouteBuilder

    # NB: from_filewatcher требует source_id через **kwargs (для FileWatcherSource).
    # Source_id — required positional arg в FileWatcherSource.__init__.
    b = RouteBuilder.from_filewatcher(
        "csv.import", path="/data/orders", recursive=True, source_id="orders_watcher"
    )
    assert b.route_id == "csv.import"


def test_route_builder_from_webhook() -> None:
    """``RouteBuilder.from_webhook`` — это instance method (smoke test)."""
    from src.backend.dsl.builders.base import RouteBuilder

    # from_webhook — instance method (self), не classmethod. Create instance
    # через from_() first, then call from_webhook().
    b = RouteBuilder.from_("webhook.test", source="webhook:/path")
    # Direct call: from_webhook(path, *, method="POST") — modifies current route
    # В текущей реализации from_webhook — мутирующий method, возвращает self
    result = b.from_webhook("/new-path", method="POST")
    assert result is b
    assert b.route_id == "webhook.test"


def test_all_from_builders_return_route_builder() -> None:
    """Все from_* builders возвращают :class:`RouteBuilder` instance.

    Comprehensive smoke test: 8+ builders создаются и возвращают валидный
    RouteBuilder с правильными attrs (``route_id``, ``source``, ``_processors``).
    """
    from src.backend.dsl.builders.base import RouteBuilder

    builders_factories = [
        ("from_", lambda: RouteBuilder.from_("test1", source="timer:60s")),
        (
            "from_registered_source",
            lambda: RouteBuilder.from_registered_source("test2", "test_source"),
        ),
        (
            "from_sse",
            lambda: RouteBuilder.from_sse("test3", "https://example.com/sse"),
        ),
        (
            "from_sse_multi",
            lambda: RouteBuilder.from_sse_multi(
                "test3m", ["https://a/sse", "https://b/sse"]
            ),
        ),
        (
            "from_telegram",
            lambda: RouteBuilder.from_telegram("test4", bot_token="123:ABC"),
        ),
        (
            "from_kafka",
            lambda: RouteBuilder.from_kafka(
                "test5",
                topic="t",
                bootstrap_servers="kafka:9092",
                group_id="g1",
            ),
        ),
        (
            "from_rabbit",
            lambda: RouteBuilder.from_rabbit(
                "test6", queue="q", url="amqp://rabbit:5672"
            ),
        ),
        (
            "from_filewatcher",
            lambda: RouteBuilder.from_filewatcher(
                "test7", path="/tmp/x", source_id="x_watcher"
            ),
        ),
    ]

    for name, factory in builders_factories:
        b = factory()
        assert isinstance(b, RouteBuilder), f"{name} returned {type(b)}"
        assert hasattr(b, "route_id"), f"{name} missing route_id"
        assert hasattr(b, "source"), f"{name} missing source"
        assert hasattr(b, "_processors"), f"{name} missing _processors"
        assert b._processors == [], f"{name} should start with empty _processors"


def test_builders_chainable() -> None:
    """Builders fluent-chainable — ``_add`` returns self."""
    from src.backend.dsl.builders.base import RouteBuilder
    from src.backend.dsl.engine.processors import CallableProcessor

    async def noop(exchange, context):  # noqa: ARG001
        return exchange

    b = RouteBuilder.from_sse("chain.test", "https://example.com/sse")
    proc = CallableProcessor(func=noop)
    result = b._add(proc)
    assert result is b
    assert len(b._processors) == 1


def test_build_pipeline_after_chain() -> None:
    """``build()`` после chain создаёт :class:`Pipeline` с правильными attrs."""
    from src.backend.dsl.builders.base import RouteBuilder
    from src.backend.dsl.engine.processors import CallableProcessor

    async def noop(exchange, context):  # noqa: ARG001
        return exchange

    b = RouteBuilder.from_sse("pipeline.test", "https://example.com/sse")
    b._add(CallableProcessor(func=noop))
    b._add(CallableProcessor(func=noop))
    pipeline = b.build()
    assert pipeline.route_id == "pipeline.test"
    assert pipeline.source == "sse:pipeline.test"
    assert len(pipeline.processors) == 2
