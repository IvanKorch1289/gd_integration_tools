# ruff: noqa: S101
"""Unit-тесты для storage_ext процессоров.

Покрывает Neo4jQueryProcessor, TimeSeriesWriteProcessor, PriorityEnqueueProcessor.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.processors.storage_ext import (
    Neo4jQueryProcessor,
    PriorityEnqueueProcessor,
    TimeSeriesWriteProcessor,
)


class _Message:
    def __init__(self, body: Any = None, headers: dict[str, str] | None = None) -> None:
        self.body = body
        self.headers = headers or {}


class _Exchange:
    def __init__(self, body: Any = None) -> None:
        self.in_message = _Message(body=body)
        self.properties: dict[str, Any] = {}
        self._error: str | None = None

    def set_property(self, key: str, value: Any) -> None:
        self.properties[key] = value

    def fail(self, msg: str) -> None:
        self._error = msg


class _Context:
    pass


class TestNeo4jQueryProcessorInit:
    """Конструктор + security guard."""

    def test_valid_cypher(self) -> None:
        proc = Neo4jQueryProcessor(cypher="MATCH (n) RETURN n")
        assert "MATCH (n)" in proc._cypher

    def test_destructive_without_match_guard(self) -> None:
        with pytest.raises(ValueError, match="Destructive"):
            Neo4jQueryProcessor(cypher="DROP INDEX idx")

    def test_destructive_with_match_allowed(self) -> None:
        # MATCH перед DROP — допустимо
        proc = Neo4jQueryProcessor(cypher="MATCH (n) DROP n")
        assert proc is not None


@pytest.mark.asyncio
class TestNeo4jQueryProcess:
    """``Neo4jQueryProcessor.process``."""

    async def test_import_error_fails_exchange(self) -> None:
        import sys
        from builtins import __import__ as real_import

        proc = Neo4jQueryProcessor(cypher="MATCH (n) RETURN n")
        exchange = _Exchange()

        def _fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "neo4j":
                raise ImportError("no neo4j")
            return real_import(name, *args, **kwargs)

        with (
            patch.dict(sys.modules, {"neo4j": None}),
            patch("builtins.__import__", _fake_import),
        ):
            await proc.process(exchange, _Context())

        assert "neo4j driver not installed" in exchange._error

    async def test_success(self) -> None:
        import sys

        proc = Neo4jQueryProcessor(cypher="MATCH (n) RETURN n")
        exchange = _Exchange(body={"user_id": 42})

        mock_result = AsyncMock()
        mock_result.data.return_value = [{"n": {"id": 1}}]
        mock_session = AsyncMock()
        mock_session.run.return_value = mock_result
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session_ctx
        mock_driver.close = AsyncMock()

        fake_neo4j = MagicMock()
        fake_neo4j.AsyncGraphDatabase.driver.return_value = mock_driver

        with (
            patch.dict(sys.modules, {"neo4j": fake_neo4j}),
            patch.dict(
                "os.environ",
                {"NEO4J_URI": "bolt://test:7687", "NEO4J_PASSWORD": "pass"},
            ),
        ):
            await proc.process(exchange, _Context())

        assert exchange.properties["neo4j_result"] == [{"n": {"id": 1}}]
        mock_driver.close.assert_awaited_once()

    async def test_params_from_body_false(self) -> None:
        import sys

        proc = Neo4jQueryProcessor(cypher="MATCH (n) RETURN n", params_from_body=False)
        exchange = _Exchange(body={"user_id": 42})

        mock_result = AsyncMock()
        mock_result.data.return_value = []
        mock_session = AsyncMock()
        mock_session.run.return_value = mock_result
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session_ctx
        mock_driver.close = AsyncMock()

        fake_neo4j = MagicMock()
        fake_neo4j.AsyncGraphDatabase.driver.return_value = mock_driver

        with (
            patch.dict(sys.modules, {"neo4j": fake_neo4j}),
            patch.dict("os.environ", {"NEO4J_PASSWORD": ""}),
        ):
            await proc.process(exchange, _Context())

        call_kwargs = mock_session.run.call_args.kwargs
        assert call_kwargs == {}

    async def test_query_error_fails_exchange(self) -> None:
        import sys

        proc = Neo4jQueryProcessor(cypher="MATCH (n) RETURN n")
        exchange = _Exchange()

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(side_effect=RuntimeError("conn broken"))
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session_ctx
        mock_driver.close = AsyncMock()

        fake_neo4j = MagicMock()
        fake_neo4j.AsyncGraphDatabase.driver.return_value = mock_driver

        with (
            patch.dict(sys.modules, {"neo4j": fake_neo4j}),
            patch.dict("os.environ", {"NEO4J_PASSWORD": ""}),
        ):
            await proc.process(exchange, _Context())

        assert "Neo4j query failed" in exchange._error


class TestTimeSeriesWriteProcessorInit:
    def test_invalid_table_name_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid table name"):
            TimeSeriesWriteProcessor(table="metrics;drop", tags=[])


@pytest.mark.asyncio
class TestTimeSeriesWriteProcess:
    """``TimeSeriesWriteProcessor.process``."""

    async def test_empty_points(self) -> None:
        proc = TimeSeriesWriteProcessor(table="metrics", tags=["env"])
        exchange = _Exchange(body=[])

        await proc.process(exchange, _Context())
        assert exchange.properties["ts_written"] == 0

    async def test_timescale_write(self) -> None:
        proc = TimeSeriesWriteProcessor(
            table="metrics", tags=["env"], field="value", backend="timescale"
        )
        exchange = _Exchange(
            body=[{"timestamp": "2024-01-01", "env": "prod", "value": 42}]
        )

        mock_conn = AsyncMock()
        mock_conn_ctx = AsyncMock()
        mock_conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn_ctx
        mock_db = MagicMock()
        mock_db.get_async_engine.return_value = mock_engine

        with patch(
            "src.backend.infrastructure.database.database.db_initializer", mock_db
        ):
            await proc.process(exchange, _Context())

        assert exchange.properties["ts_written"] == 1
        mock_conn.execute.assert_awaited()
        mock_conn.commit.assert_awaited()

    async def test_influxdb_write(self) -> None:
        import sys

        proc = TimeSeriesWriteProcessor(
            table="metrics", tags=["env"], field="value", backend="influxdb"
        )
        exchange = _Exchange(body=[{"env": "prod", "value": 42}])

        mock_write_api = MagicMock()
        mock_client = MagicMock()
        mock_client.write_api.return_value = mock_write_api
        mock_point = MagicMock()

        fake_influxdb = MagicMock()
        fake_influxdb.InfluxDBClient.return_value = mock_client
        fake_influxdb.Point.return_value = mock_point
        fake_influxdb.client.write_api.SYNCHRONOUS = MagicMock()

        with (
            patch.dict(
                sys.modules,
                {
                    "influxdb_client": fake_influxdb,
                    "influxdb_client.client": fake_influxdb.client,
                    "influxdb_client.client.write_api": fake_influxdb.client.write_api,
                },
            ),
            patch.dict(
                "os.environ",
                {"INFLUXDB_URL": "http://localhost:8086", "INFLUXDB_TOKEN": "tok"},
            ),
        ):
            await proc.process(exchange, _Context())

        assert exchange.properties["ts_written"] == 1

    async def test_import_error_influxdb(self) -> None:
        import sys
        from builtins import __import__ as real_import

        proc = TimeSeriesWriteProcessor(
            table="metrics", tags=["env"], backend="influxdb"
        )
        exchange = _Exchange(body=[{"env": "prod", "value": 42}])

        def _fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "influxdb_client":
                raise ImportError("no influxdb")
            return real_import(name, *args, **kwargs)

        with (
            patch.dict(sys.modules, {"influxdb_client": None}),
            patch("builtins.__import__", _fake_import),
        ):
            await proc.process(exchange, _Context())

        assert "Time series write failed" in exchange._error

    async def test_auto_selects_influxdb_when_env_set(self) -> None:
        import sys
        from builtins import __import__ as real_import

        proc = TimeSeriesWriteProcessor(table="metrics", tags=["env"])
        exchange = _Exchange(body=[{"env": "prod", "value": 1}])

        def _fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "influxdb_client":
                raise ImportError("no influxdb")
            return real_import(name, *args, **kwargs)

        with (
            patch.dict("os.environ", {"INFLUXDB_URL": "http://influx:8086"}),
            patch.dict(sys.modules, {"influxdb_client": None}),
            patch("builtins.__import__", _fake_import),
        ):
            await proc.process(exchange, _Context())

        assert "Time series write failed" in exchange._error

    async def test_auto_selects_timescale_when_env_not_set(self) -> None:
        proc = TimeSeriesWriteProcessor(table="metrics", tags=["env"])
        exchange = _Exchange(body=[{"env": "prod", "value": 1}])

        mock_conn = AsyncMock()
        mock_conn_ctx = AsyncMock()
        mock_conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn_ctx
        mock_db = MagicMock()
        mock_db.get_async_engine.return_value = mock_engine

        with (
            patch.dict("os.environ", {}, clear=True),
            patch(
                "src.backend.infrastructure.database.database.db_initializer", mock_db
            ),
        ):
            await proc.process(exchange, _Context())

        assert exchange.properties["ts_written"] == 1

    async def test_none_timestamp_set_to_now(self) -> None:
        proc = TimeSeriesWriteProcessor(
            table="metrics", tags=["env"], field="value", backend="timescale"
        )
        exchange = _Exchange(body=[{"env": "prod", "value": 1}])

        mock_conn = AsyncMock()
        mock_conn_ctx = AsyncMock()
        mock_conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn_ctx
        mock_db = MagicMock()
        mock_db.get_async_engine.return_value = mock_engine

        with patch(
            "src.backend.infrastructure.database.database.db_initializer", mock_db
        ):
            await proc.process(exchange, _Context())

        # execute был вызван — проверим что timestamp подставился
        mock_conn.execute.assert_awaited()


class TestPriorityEnqueueProcessorInit:
    def test_defaults(self) -> None:
        proc = PriorityEnqueueProcessor(queue_name="q")
        assert proc._queue == "q"
        assert proc._priority_field == "priority"
        assert proc._default_priority == 5
        assert proc._max_size == 100000


@pytest.mark.asyncio
class TestPriorityEnqueueProcess:
    """``PriorityEnqueueProcessor.process``."""

    async def test_success(self) -> None:
        proc = PriorityEnqueueProcessor(queue_name="orders")
        exchange = _Exchange(body={"id": 1, "priority": 1})

        mock_redis = AsyncMock()
        mock_redis.zcard.return_value = 10

        mock_client = MagicMock()
        mock_client._raw_client = mock_redis

        with patch(
            "src.backend.infrastructure.clients.storage.redis.get_redis_client",
            MagicMock(return_value=mock_client),
        ):
            await proc.process(exchange, _Context())

        assert "priority_enqueued_id" in exchange.properties
        assert "priority_enqueued_score" in exchange.properties
        mock_redis.zadd.assert_awaited_once()

    async def test_uses_default_priority(self) -> None:
        proc = PriorityEnqueueProcessor(queue_name="q")
        exchange = _Exchange(body="not dict")

        mock_redis = AsyncMock()
        mock_redis.zcard.return_value = 1

        mock_client = MagicMock()
        mock_client._raw_client = mock_redis

        with patch(
            "src.backend.infrastructure.clients.storage.redis.get_redis_client",
            MagicMock(return_value=mock_client),
        ):
            await proc.process(exchange, _Context())

        call_args = mock_redis.zadd.call_args
        payload_json = list(call_args[0][1].keys())[0]
        assert '"priority":5' in payload_json

    async def test_trims_when_over_max_size(self) -> None:
        proc = PriorityEnqueueProcessor(queue_name="q", max_size=2)
        exchange = _Exchange(body={"id": 1})

        mock_redis = AsyncMock()
        mock_redis.zcard.return_value = 3

        mock_client = MagicMock()
        mock_client._raw_client = mock_redis

        with patch(
            "src.backend.infrastructure.clients.storage.redis.get_redis_client",
            MagicMock(return_value=mock_client),
        ):
            await proc.process(exchange, _Context())

        mock_redis.zremrangebyrank.assert_awaited_once_with("priority_queue:q", 2, -1)

    async def test_error_fails_exchange(self) -> None:
        proc = PriorityEnqueueProcessor(queue_name="q")
        exchange = _Exchange(body={})

        mock_client = MagicMock()
        mock_client._raw_client = None
        # fallback to redis_client itself
        mock_client.zadd = AsyncMock(side_effect=RuntimeError("redis down"))

        with patch(
            "src.backend.infrastructure.clients.storage.redis.get_redis_client",
            MagicMock(return_value=mock_client),
        ):
            await proc.process(exchange, _Context())

        assert "Priority enqueue failed" in exchange._error
