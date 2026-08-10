"""Unit tests for src.backend.dsl.builders.infrastructure_dsl (K3 W4, S38 → S175 #5 hybrid).

S175 #5: hybrid resolution of audit-warning vs deletion conflict.
- 7 phantom stubs DELETED (replaced by infra_* / storage/s3.py).
- 8 phantom stubs KEPT with audit-warning observability
  (no real replacement yet for: Redis Set/Delete, ClickHouse Insert,
  ES Index/Search, Mongo Insert/Find-partial, SFTP Get/Put).

This tests:
- WRAPPER methods (chainable) for kept stubs.
- to_spec() round-trip for kept stubs.
- audit-warning observability for kept stubs.
- DELETED stubs are NO LONGER importable (regression guard).

Real backend processors (InfraRedisGetProcessor, InfraClickHouseQueryProcessor,
InfraS3GetProcessor, FromS3Processor, etc.) тестируются отдельно в
src/backend/dsl/engine/processors/infra_*.py.
"""

from __future__ import annotations

import pytest

from src.backend.dsl.builders.base import RouteBuilder
from src.backend.dsl.builders.infrastructure_dsl import (
    # Kept stubs (S175 #5 hybrid — no real impl yet).
    ClickHouseInsertProcessor,
    ElasticsearchIndexProcessor,
    ElasticsearchSearchProcessor,
    InfrastructureDSL,
    MongoFindProcessor,
    MongoInsertProcessor,
    RedisDeleteProcessor,
    RedisSetProcessor,
    SftpGetProcessor,
    SftpPutProcessor,
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

    def test_method_count_s175_hybrid(self) -> None:
        """S175 #5: 9 kept wrapper methods (deleted 5)."""
        methods = [m for m in dir(InfrastructureDSL) if not m.startswith("_")]
        # KEPT methods (после S175 #5 hybrid).
        expected_kept = {
            "redis_set",
            "redis_delete",
            "clickhouse_insert",
            "es_index",
            "es_search",
            "mongo_insert",
            "mongo_find",
            "sftp_get",
            "sftp_put",
        }
        for m in expected_kept:
            assert m in methods, f"Missing kept method: {m}"

        # DELETED methods (S175 #5 hybrid — moved to infra_*).
        deleted = {
            "redis_get",  # InfraRedisGetProcessor
            "clickhouse_query",  # InfraClickHouseQueryProcessor
            "s3_put",  # ToS3Processor
            "s3_get",  # FromS3Processor
            "s3_delete",  # S3DeleteProcessor (storage/s3.py)
            "s3_list",  # S3ListProcessor (storage/s3.py)
            "sql_exec",  # InfraDbQueryProcessor
        }
        for m in deleted:
            assert m not in methods, f"Deleted method still present: {m}"


class TestDeletedStubsRegression:
    """S175 #5: DELETED stubs не должны импортироваться."""

    def test_deleted_stubs_not_importable(self) -> None:
        """Verify 7 DELETED stub classes raised ImportError."""
        deleted_names = [
            "RedisGetProcessor",
            "ClickHouseQueryProcessor",
            "S3PutProcessor",
            "S3GetProcessor",
            "S3DeleteProcessor",
            "S3ListProcessor",
            "SqlExecProcessor",
        ]
        from src.backend.dsl.builders import infrastructure_dsl

        for name in deleted_names:
            assert not hasattr(infrastructure_dsl, name), (
                f"DELETED stub {name} still present in infrastructure_dsl module"
            )

    def test_all_public_exports_only_kept_stubs(self) -> None:
        """`__all__` содержит только 10 KEPT классов."""
        from src.backend.dsl.builders import infrastructure_dsl

        expected = {
            "ClickHouseInsertProcessor",
            "ElasticsearchIndexProcessor",
            "ElasticsearchSearchProcessor",
            "InfrastructureDSL",
            "MongoFindProcessor",
            "MongoInsertProcessor",
            "RedisDeleteProcessor",
            "RedisSetProcessor",
            "SftpGetProcessor",
            "SftpPutProcessor",
        }
        assert set(infrastructure_dsl.__all__) == expected, (
            f"__all__ mismatch: got {set(infrastructure_dsl.__all__)}, expected {expected}"
        )


class TestKeptRedisMethods:
    def test_redis_set_basic(self, builder: RouteBuilder) -> None:
        result = builder.redis_set("key1", "value1")
        assert isinstance(result, RouteBuilder)
        assert isinstance(builder._processors[-1], RedisSetProcessor)

    def test_redis_set_with_ttl(self, builder: RouteBuilder) -> None:
        builder.redis_set("k", "v", ttl_seconds=60)
        proc = builder._processors[-1]
        assert proc.params["ttl_seconds"] == 60

    def test_redis_delete(self, builder: RouteBuilder) -> None:
        builder.redis_delete("k")
        assert isinstance(builder._processors[-1], RedisDeleteProcessor)


class TestKeptClickHouseMethods:
    def test_clickhouse_insert(self, builder: RouteBuilder) -> None:
        builder.clickhouse_insert("events")
        assert isinstance(builder._processors[-1], ClickHouseInsertProcessor)

    def test_clickhouse_insert_batch_size(self, builder: RouteBuilder) -> None:
        builder.clickhouse_insert("events", batch_size=5000)
        assert builder._processors[-1].params["batch_size"] == 5000


class TestKeptElasticsearchMethods:
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


class TestKeptMongoMethods:
    def test_mongo_insert(self, builder: RouteBuilder) -> None:
        builder.mongo_insert("users")
        assert isinstance(builder._processors[-1], MongoInsertProcessor)

    def test_mongo_find(self, builder: RouteBuilder) -> None:
        builder.mongo_find("users", {"active": True}, to_property="docs")
        proc = builder._processors[-1]
        assert isinstance(proc, MongoFindProcessor)
        assert proc.params["to_property"] == "docs"


class TestKeptSFTPMethods:
    def test_sftp_get(self, builder: RouteBuilder) -> None:
        builder.sftp_get(
            "host.example.com",
            "/remote/path",
            username="user",
            key_file="/path/to/key",
        )
        proc = builder._processors[-1]
        assert isinstance(proc, SftpGetProcessor)
        assert proc.params["host"] == "host.example.com"
        assert proc.params["remote_path"] == "/remote/path"

    def test_sftp_put(self, builder: RouteBuilder) -> None:
        builder.sftp_put(
            "host.example.com",
            "/remote/path",
            body_from="body",
            username="user",
        )
        proc = builder._processors[-1]
        assert isinstance(proc, SftpPutProcessor)
        assert proc.params["host"] == "host.example.com"


class TestKeptStubsAuditWarning:
    """S175 M5.3: kept stubs emit audit-warning через _stub_logger."""

    @pytest.mark.asyncio
    async def test_redis_set_emits_warning_on_execute(self) -> None:
        """Audit-warning emitted when stub executes (per parallel WIP)."""
        import logging

        from src.backend.dsl.engine.exchange import Exchange, Message

        captured: list[str] = []

        class _CaptureHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(record.getMessage())

        logger = logging.getLogger("dsl.infrastructure_dsl.stub")
        logger.addHandler(_CaptureHandler())
        try:
            proc = RedisSetProcessor(key="k", value="v")
            exchange = Exchange(
                in_message=Message(body=None, headers={}),
                properties={},
            )
            await proc.process(exchange, context=None)
            assert any("redis_set" in msg for msg in captured), (
                f"Audit-warning должен содержать op_name=redis_set, got {captured}"
            )
        finally:
            logger.removeHandler(_CaptureHandler())

    @pytest.mark.asyncio
    async def test_sftp_get_emits_warning_on_execute(self) -> None:
        """SFTP stub тоже audit-warning."""
        import logging

        from src.backend.dsl.engine.exchange import Exchange, Message

        captured: list[str] = []

        class _CaptureHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(record.getMessage())

        logger = logging.getLogger("dsl.infrastructure_dsl.stub")
        logger.addHandler(_CaptureHandler())
        try:
            proc = SftpGetProcessor(host="h", remote_path="/p")
            exchange = Exchange(
                in_message=Message(body=None, headers={}),
                properties={},
            )
            await proc.process(exchange, context=None)
            assert any("sftp_get" in msg for msg in captured)
        finally:
            logger.removeHandler(_CaptureHandler())


class TestChainingAndIntegration:
    def test_keeps_chainable_return_self(self, builder: RouteBuilder) -> None:
        """Каждый kept wrapper возвращает self (RouteBuilder)."""
        result = (
            builder.redis_set("k", "v")
            .redis_delete("k")
            .clickhouse_insert("t")
            .es_index("i")
            .es_search("i", {})
            .mongo_insert("c")
            .mongo_find("c", {})
            .sftp_get("h", "/p")
            .sftp_put("h", "/p")
        )
        assert result is builder
        # 9 wrappers added.
        assert len(builder._processors) == 9

    def test_to_spec_round_trip(self, builder: RouteBuilder) -> None:
        builder.redis_set("k", "v", ttl_seconds=30)
        spec = builder._processors[-1].to_spec()
        assert spec is not None
        assert "redis_set" in spec
        assert spec["redis_set"]["key"] == "k"
        assert spec["redis_set"]["ttl_seconds"] == 30
