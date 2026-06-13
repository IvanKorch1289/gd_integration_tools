# ruff: noqa: S101
"""S106 W4 — tests для ``RouteBuilder.from_nats()`` + ``RouteBuilder.from_mongo()``.

Покрытие:

* DSL registration: classmethod создаёт RouteBuilder с правильным source URI;
* Smoke-валидация конструктора source (S50 W2 pattern, как from_webdav);
* Source ID format (``nats:{subject}`` / ``mongo:{db}/{collection}``);
* Validation: Mongo отвергает пустые connection_url/database, NATS —
  пустой subject.
* Wildcard subject для NATS.
* collection="" для Mongo → watch на уровне database.
"""

from __future__ import annotations

import pytest

from src.backend.dsl.builders.base import RouteBuilder
from src.backend.infrastructure.sources.mongo import MongoSource, MongoSourceConfig
from src.backend.infrastructure.sources.nats import NatsSource


# ── from_nats ──


def test_from_nats_creates_route_builder_with_nats_source_uri() -> None:
    """``RouteBuilder.from_nats(...)`` — source URI = ``nats:{subject}``."""
    route = RouteBuilder.from_nats(
        "metrics.consumer",
        subject="metrics.app.>",
    )
    assert isinstance(route, RouteBuilder)
    assert route.source == "nats:metrics.app.>"
    assert route.route_id == "metrics.consumer"


def test_from_nats_with_description() -> None:
    """Description пробрасывается в RouteBuilder."""
    route = RouteBuilder.from_nats(
        "x", subject="y", description="metrics intake"
    )
    assert route.description == "metrics intake"


def test_from_nats_smoke_validates_nats_source_constructor() -> None:
    """``from_nats`` создаёт NatsSource для smoke-валидации (без exception)."""
    # Просто проверим что NatsSource может быть инстанциирован с теми же args
    src = NatsSource(subject="orders.created", nats_url="nats://other:4222")
    assert src.source_id == "nats:orders.created"
    assert src.kind.value == "mq"


def test_from_nats_supports_wildcard_subjects() -> None:
    """NATS wildcards ``*`` и ``>`` принимаются без ошибок."""
    for subject in ["metrics.*", "orders.>", "single", "a.b.c.d"]:
        src = NatsSource(subject=subject)
        assert src.source_id == f"nats:{subject}"


def test_from_nats_source_rejects_empty_subject() -> None:
    """NatsSource с пустым subject → ValueError (защита от silent)."""
    with pytest.raises(ValueError, match="subject обязателен"):
        NatsSource(subject="")


# ── from_mongo ──


def test_from_mongo_creates_route_builder_with_mongo_source_uri() -> None:
    """``RouteBuilder.from_mongo(...)`` — source URI = ``mongo:{db}/{coll}``."""
    route = RouteBuilder.from_mongo(
        "orders.changes",
        connection_url="mongodb://localhost:27017",
        database="shop",
        collection="orders",
    )
    assert isinstance(route, RouteBuilder)
    assert route.source == "mongo:shop/orders"
    assert route.route_id == "orders.changes"


def test_from_mongo_with_empty_collection_uses_wildcard() -> None:
    """``collection=""`` → source URI = ``mongo:db/*`` (watch на уровне database)."""
    route = RouteBuilder.from_mongo(
        "all.changes",
        connection_url="mongodb://localhost:27017",
        database="shop",
        collection="",
    )
    assert route.source == "mongo:shop/*"


def test_from_mongo_with_description() -> None:
    """Description пробрасывается в RouteBuilder."""
    route = RouteBuilder.from_mongo(
        "x",
        connection_url="mongodb://localhost:27017",
        database="db",
        collection="c",
        description="orders CDC",
    )
    assert route.description == "orders CDC"


def test_from_mongo_full_document_lookup_flag() -> None:
    """``full_document_lookup=True`` сохраняется в MongoSourceConfig."""
    cfg = MongoSourceConfig(
        connection_url="mongodb://localhost:27017",
        database="shop",
        collection="orders",
        full_document_lookup=True,
    )
    assert cfg.full_document_lookup is True


def test_from_mongo_with_pipeline() -> None:
    """Mongo aggregation pipeline сохраняется в config."""
    pipeline = [{"$match": {"operationType": "insert"}}]
    cfg = MongoSourceConfig(
        connection_url="mongodb://localhost:27017",
        database="shop",
        collection="orders",
        pipeline=pipeline,
    )
    assert cfg.pipeline == pipeline


def test_from_mongo_smoke_validates_constructor() -> None:
    """``from_mongo`` создаёт MongoSource для smoke-валидации."""
    cfg = MongoSourceConfig(
        connection_url="mongodb://localhost:27017",
        database="shop",
        collection="orders",
    )
    src = MongoSource(cfg)
    assert src.source_id == "mongo:shop/orders"
    assert src.kind.value == "cdc"


def test_from_mongo_source_rejects_empty_connection_url() -> None:
    """MongoSource с пустым connection_url → ValueError."""
    cfg = MongoSourceConfig(
        connection_url="", database="db", collection="c"
    )
    with pytest.raises(ValueError, match="connection_url обязателен"):
        MongoSource(cfg)


def test_from_mongo_source_rejects_empty_database() -> None:
    """MongoSource с пустым database → ValueError."""
    cfg = MongoSourceConfig(
        connection_url="mongodb://x", database="", collection="c"
    )
    with pytest.raises(ValueError, match="database обязателен"):
        MongoSource(cfg)


# ── SourceKind правильность ──


def test_nats_source_kind_is_mq() -> None:
    """NatsSource.kind = SourceKind.MQ (NATS — MQ, не HTTP/CDC)."""
    src = NatsSource(subject="x")
    assert src.kind.value == "mq"


def test_mongo_source_kind_is_cdc() -> None:
    """MongoSource.kind = SourceKind.CDC (change streams — CDC pattern)."""
    src = MongoSource(
        MongoSourceConfig(connection_url="mongodb://x", database="d", collection="c")
    )
    assert src.kind.value == "cdc"
