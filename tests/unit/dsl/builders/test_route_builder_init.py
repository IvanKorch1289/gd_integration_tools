"""S97 W1 — regression-блокировка для RouteBuilder.__init__ fix.

Pre-S97: ``RouteBuilder`` имел ``__slots__=()`` и **нет** ``__init__``,
поэтому ``from_`` (``cls(route_id=..., source=..., description=...)``)
→ ``TypeError: RouteBuilder() takes no arguments``.

S97 W1 fix: explicit ``__init__(route_id, source, description)`` + 8 slots
для instance attrs (route_id, source, description, _description, processors,
_protocol, _transport_config, _feature_flag).

Тесты:

1. ``__init__`` принимает (route_id, source, description).
2. ``__init__`` no-args — backward compat (default values).
3. ``from_`` возвращает RouteBuilder с правильными attrs.
4. ``from_registered_source`` — аналогично.
5. ``from_sse`` (mixin method) — actual DSL integration, не TypeError.
6. ``from_sse_multi`` (S96 W4 builder) — multi-source.
7. ``build()`` работает на instantiated builder.
8. ``_add(processor)`` — fluent chain.
"""

from __future__ import annotations


def test_route_builder_init_with_args() -> None:
    """``__init__(route_id, source, description)``."""
    from src.backend.dsl.builders.base import RouteBuilder

    b = RouteBuilder(
        route_id="orders.create",
        source="kafka:orders",
        description="Order creation consumer",
    )
    assert b.route_id == "orders.create"
    assert b.source == "kafka:orders"
    assert b.description == "Order creation consumer"


def test_from_creates_builder() -> None:
    """``RouteBuilder.from_`` создаёт валидный instance."""
    from src.backend.dsl.builders.base import RouteBuilder

    b = RouteBuilder.from_(
        "etl.import", source="timer:300s", description="Periodic ETL"
    )
    assert b.route_id == "etl.import"
    assert b.source == "timer:300s"
    assert b.description == "Periodic ETL"


def test_from_registered_source_creates_builder() -> None:
    """``from_registered_source`` создаёт builder с ``source:<id>``."""
    from src.backend.dsl.builders.base import RouteBuilder

    b = RouteBuilder.from_registered_source("orders.audit", "orders_cdc")
    assert b.route_id == "orders.audit"
    assert b.source == "source:orders_cdc"


def test_from_sse_instantiates() -> None:
    """``RouteBuilder.from_sse`` — DSL integration, S94 W4 orphan fixed."""
    from src.backend.dsl.builders.base import RouteBuilder

    b = RouteBuilder.from_sse(
        "test.stream", "https://example.com/events", parse_json=False
    )
    assert b.route_id == "test.stream"
    assert b.source == "sse:test.stream"
    assert hasattr(b, "_sse_source")
    assert b._sse_source is not None


def test_from_sse_multi_instantiates() -> None:
    """``RouteBuilder.from_sse_multi`` — multi-stream DSL integration."""
    from src.backend.dsl.builders.base import RouteBuilder

    urls = [
        "https://tenant-a.example.com/events",
        "https://tenant-b.example.com/events",
    ]
    b = RouteBuilder.from_sse_multi("multi.tenant", urls, merge_strategy="interleave")
    assert b.route_id == "multi.tenant.multi"
    assert b.source == "sse-multi:multi.tenant.multi"
    sources, strategy = b._sse_multi_source
    assert len(sources) == 2
    assert strategy == "interleave"


def test_build_returns_pipeline() -> None:
    """``build()`` создаёт Pipeline из накопленных processors."""
    from src.backend.dsl.builders.base import RouteBuilder

    b = RouteBuilder.from_("test.build", source="timer:60s")
    pipeline = b.build()
    assert pipeline.route_id == "test.build"
    assert pipeline.source == "timer:60s"


def test_fluent_chain_add_processor() -> None:
    """``_add(processor)`` appends и returns self."""
    from src.backend.dsl.builders.base import RouteBuilder
    from src.backend.dsl.engine.processors import CallableProcessor

    async def my_proc(exchange, context):  # noqa: ARG001
        return exchange

    b = RouteBuilder.from_("test.fluent", source="timer:60s")
    proc = CallableProcessor(func=my_proc)
    result = b._add(proc)
    assert result is b
    assert b._processors == [proc]


def test_route_builder_slots_have_declared_attrs() -> None:
    """``__slots__`` содержит declared attrs (smoke test)."""
    from src.backend.dsl.builders.base import RouteBuilder

    declared = set(RouteBuilder.__slots__)
    # All internal state attrs должны быть в __slots__
    assert "_processors" in declared
    assert "_protocol" in declared
    assert "_transport_config" in declared
    assert "_feature_flag" in declared
    # Public API attrs
    assert "route_id" in declared
    assert "source" in declared
    assert "description" in declared
