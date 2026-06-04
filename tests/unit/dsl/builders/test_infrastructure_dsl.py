"""Unit tests for src.backend.dsl.builders.infrastructure_dsl (K3 W4, S38).

Subagent #1 created infrastructure_dsl.py (~230 LOC) but hit
max_iterations before test creation + MRO integration. Orchestrator:
- added InfrastructureDSL to RouteBuilder MRO
- created 17 tests
- verified + commit

This tests the WRAPPER methods (chainable) + to_spec, NOT the
underlying backend processors (those need real Redis/ClickHouse/etc).
"""

from __future__ import annotations

import pytest

from src.backend.dsl.builders.base import RouteBuilder
from src.backend.dsl.builders.infrastructure_dsl import (
    ClickHouseInsertProcessor,
    ClickHouseQueryProcessor,
    ElasticsearchIndexProcessor,
    ElasticsearchSearchProcessor,
    InfrastructureDSL,
    MongoFindProcessor,
    MongoInsertProcessor,
    RedisDeleteProcessor,
    RedisGetProcessor,
    RedisSetProcessor,
    S3PutProcessor,
    SqlExecProcessor,
)


@pytest.fixture
def builder() -> RouteBuilder:
    return RouteBuilder(route_id="test_infra", source="internal:test")


class TestInfrastructureDSLInMRO:
    def test_in_mro(self) -> None:
        mro = [c.__name__ for c in RouteBuilder.__mro__]
        assert "InfrastructureDSL" in mro

    def test_slots(self) -> None:
        assert InfrastructureDSL.__slots__ == ()

    def test_method_count(self) -> None:
        methods = [m for m in dir(InfrastructureDSL) if not m.startswith("_")]
        expected = [
            "redis_set",
            "redis_get",
            "redis_delete",
            "clickhouse_insert",
            "clickhouse_query",
            "es_index",
            "es_search",
            "mongo_insert",
            "mongo_find",
            "s3_put",
            "sql_exec",
        ]
        for m in expected:
            assert m in methods, f"Missing method: {m}"


class TestRedisMethods:
    def test_redis_set_basic(self, builder: RouteBuilder) -> None:
        result = builder.redis_set("key1", "value1")
        assert isinstance(result, RouteBuilder)
        assert isinstance(builder._processors[-1], RedisSetProcessor)

    def test_redis_set_with_ttl(self, builder: RouteBuilder) -> None:
        builder.redis_set("k", "v", ttl_seconds=60)
        proc = builder._processors[-1]
        assert proc.params["ttl_seconds"] == 60

    def test_redis_get_with_default(self, builder: RouteBuilder) -> None:
        builder.redis_get("missing", default="fallback")
        proc = builder._processors[-1]
        assert isinstance(proc, RedisGetProcessor)
        assert proc.params["default"] == "fallback"

    def test_redis_delete(self, builder: RouteBuilder) -> None:
        builder.redis_delete("k")
        assert isinstance(builder._processors[-1], RedisDeleteProcessor)


class TestClickHouseMethods:
    def test_clickhouse_insert(self, builder: RouteBuilder) -> None:
        builder.clickhouse_insert("events")
        assert isinstance(builder._processors[-1], ClickHouseInsertProcessor)

    def test_clickhouse_insert_batch_size(self, builder: RouteBuilder) -> None:
        builder.clickhouse_insert("events", batch_size=5000)
        assert builder._processors[-1].params["batch_size"] == 5000

    def test_clickhouse_query(self, builder: RouteBuilder) -> None:
        builder.clickhouse_query("SELECT 1", to_property="result")
        proc = builder._processors[-1]
        assert isinstance(proc, ClickHouseQueryProcessor)
        assert proc.params["to_property"] == "result"


class TestElasticsearchMethods:
    def test_es_index(self, builder: RouteBuilder) -> None:
        builder.es_index("my_index")
        assert isinstance(builder._processors[-1], ElasticsearchIndexProcessor)

    def test_es_index_auto_id(self, builder: RouteBuilder) -> None:
        builder.es_index("idx", doc_id_from=None)
        proc = builder._processors[-1]
        assert proc.params["doc_id_from"] is None

    def test_es_search(self, builder: RouteBuilder) -> None:
        builder.es_search("idx", {"query": {"match_all": {}}}, size=20)
        proc = builder._processors[-1]
        assert isinstance(proc, ElasticsearchSearchProcessor)
        assert proc.params["size"] == 20


class TestMongoMethods:
    def test_mongo_insert(self, builder: RouteBuilder) -> None:
        builder.mongo_insert("users")
        assert isinstance(builder._processors[-1], MongoInsertProcessor)

    def test_mongo_find(self, builder: RouteBuilder) -> None:
        builder.mongo_find("users", {"active": True}, to_property="docs")
        proc = builder._processors[-1]
        assert isinstance(proc, MongoFindProcessor)
        assert proc.params["to_property"] == "docs"


class TestS3AndSQL:
    def test_s3_put(self, builder: RouteBuilder) -> None:
        builder.s3_put("path/key.json")
        assert isinstance(builder._processors[-1], S3PutProcessor)

    def test_sql_exec(self, builder: RouteBuilder) -> None:
        builder.sql_exec("DELETE FROM x", params={"id": 1})
        proc = builder._processors[-1]
        assert isinstance(proc, SqlExecProcessor)
        assert proc.params["params"] == {"id": 1}


class TestChainingAndIntegration:
    def test_all_chainable(self, builder: RouteBuilder) -> None:
        """Every method returns self (RouteBuilder)."""
        result = (
            builder.redis_set("k", "v")
            .redis_get("k")
            .redis_delete("k")
            .clickhouse_insert("t")
            .clickhouse_query("SELECT 1")
            .es_index("i")
            .es_search("i", {})
            .mongo_insert("c")
            .mongo_find("c", {})
            .s3_put("k")
            .sql_exec("SELECT 1")
        )
        assert result is builder
        assert len(builder._processors) == 11

    def test_to_spec_round_trip(self, builder: RouteBuilder) -> None:
        builder.redis_set("k", "v", ttl_seconds=30)
        spec = builder._processors[-1].to_spec()
        assert spec is not None
        assert "redis_set" in spec
        assert spec["redis_set"]["key"] == "k"
        assert spec["redis_set"]["ttl_seconds"] == 30
