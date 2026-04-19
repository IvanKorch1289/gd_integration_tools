"""Storage extensions — Graph DB (Neo4j), Time Series (InfluxDB), Priority Queue.

Все клиенты lazy-imported. Graceful fallback если библиотеки не установлены.
"""

from __future__ import annotations

import logging
from typing import Any

from app.dsl.engine.context import ExecutionContext
from app.dsl.engine.exchange import Exchange
from app.dsl.engine.processors.base import BaseProcessor

__all__ = (
    "Neo4jQueryProcessor",
    "TimeSeriesWriteProcessor",
    "PriorityEnqueueProcessor",
)

logger = logging.getLogger("dsl.storage_ext")


class Neo4jQueryProcessor(BaseProcessor):
    """Neo4j Cypher query processor.

    Usage::
        .neo4j_query(
            cypher="MATCH (u:User {id: $user_id})-[:ORDERED]->(o) RETURN o",
            params_from_body=True,
        )
    """

    def __init__(
        self,
        *,
        cypher: str,
        params_from_body: bool = True,
        output_property: str = "neo4j_result",
        connection_key: str = "neo4j_default",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"neo4j:{cypher[:40]}")
        self._cypher = cypher
        self._params_from_body = params_from_body
        self._output = output_property
        self._connection_key = connection_key

        # Security: only safe cypher keywords
        stripped = cypher.strip().upper()
        forbidden = ("DROP ", "DELETE DETACH ", "REMOVE ")
        for kw in forbidden:
            if kw in stripped and "MATCH" not in stripped[:stripped.find(kw)]:
                raise ValueError(f"Destructive Cypher without MATCH guard rejected: {kw}")

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        try:
            from neo4j import AsyncGraphDatabase
        except ImportError:
            exchange.fail("neo4j driver not installed")
            return

        import os
        uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        user = os.environ.get("NEO4J_USER", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD", "")

        params = {}
        if self._params_from_body:
            body = exchange.in_message.body
            if isinstance(body, dict):
                params = body

        try:
            driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
            async with driver.session() as session:
                result = await session.run(self._cypher, params)
                records = [dict(r) for r in await result.data()]
            await driver.close()
            exchange.set_property(self._output, records)
        except Exception as exc:
            exchange.fail(f"Neo4j query failed: {exc}")


class TimeSeriesWriteProcessor(BaseProcessor):
    """Write to TimescaleDB или InfluxDB (auto-detect по ENV).

    TimescaleDB: использует существующий PG engine.
    InfluxDB: через influxdb-client-python.

    Usage::
        .timeseries_write(table="metrics", tags=["service", "env"], field="value")
    """

    def __init__(
        self,
        *,
        table: str,
        tags: list[str],
        field: str = "value",
        timestamp_field: str | None = None,
        backend: str = "auto",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"ts_write:{table}")
        self._table = table
        self._tags = tags
        self._field = field
        self._timestamp_field = timestamp_field
        self._backend = backend

        if not table.replace("_", "").isalnum():
            raise ValueError(f"Invalid table name: {table}")

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        import os
        backend = self._backend
        if backend == "auto":
            backend = "influxdb" if os.environ.get("INFLUXDB_URL") else "timescale"

        body = exchange.in_message.body
        points = body if isinstance(body, list) else [body] if isinstance(body, dict) else []

        if not points:
            exchange.set_property("ts_written", 0)
            return

        try:
            if backend == "influxdb":
                await self._write_influxdb(points)
            else:
                await self._write_timescale(points)
            exchange.set_property("ts_written", len(points))
        except Exception as exc:
            exchange.fail(f"Time series write failed: {exc}")

    async def _write_timescale(self, points: list[dict]) -> None:
        from sqlalchemy import text

        from app.infrastructure.database.database import db_initializer

        engine = db_initializer.get_async_engine()
        columns = ["timestamp", *self._tags, self._field]
        placeholders = ", ".join(f":{c}" for c in columns)
        col_names = ", ".join(columns)
        sql = f"INSERT INTO {self._table} ({col_names}) VALUES ({placeholders})"

        async with engine.connect() as conn:
            for point in points:
                row = {c: point.get(c) for c in columns}
                if row["timestamp"] is None:
                    from datetime import UTC, datetime
                    row["timestamp"] = datetime.now(UTC)
                await conn.execute(text(sql), row)
            await conn.commit()

    async def _write_influxdb(self, points: list[dict]) -> None:
        try:
            from influxdb_client import InfluxDBClient, Point
            from influxdb_client.client.write_api import SYNCHRONOUS
        except ImportError:
            raise RuntimeError("influxdb-client not installed")

        import os
        url = os.environ.get("INFLUXDB_URL", "http://localhost:8086")
        token = os.environ.get("INFLUXDB_TOKEN", "")
        org = os.environ.get("INFLUXDB_ORG", "default")
        bucket = os.environ.get("INFLUXDB_BUCKET", self._table)

        with InfluxDBClient(url=url, token=token, org=org) as client:
            write_api = client.write_api(write_options=SYNCHRONOUS)
            for point_data in points:
                p = Point(self._table)
                for tag in self._tags:
                    if tag in point_data:
                        p.tag(tag, str(point_data[tag]))
                if self._field in point_data:
                    p.field(self._field, float(point_data[self._field]))
                write_api.write(bucket=bucket, record=p)


class PriorityEnqueueProcessor(BaseProcessor):
    """Enqueue сообщение в priority queue (Redis sorted set).

    Позже consumer читает по priority (score).

    Usage::
        .priority_enqueue(queue_name="orders.urgent", priority_field="priority")
    """

    def __init__(
        self,
        *,
        queue_name: str,
        priority_field: str = "priority",
        default_priority: int = 5,
        max_size: int = 100000,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"priority_enqueue:{queue_name}")
        self._queue = queue_name
        self._priority_field = priority_field
        self._default_priority = default_priority
        self._max_size = max_size

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        import uuid

        import orjson

        body = exchange.in_message.body
        priority = self._default_priority
        if isinstance(body, dict):
            priority = int(body.get(self._priority_field, self._default_priority))

        msg_id = str(uuid.uuid4())
        payload = orjson.dumps({
            "id": msg_id,
            "body": body,
            "headers": dict(exchange.in_message.headers),
            "priority": priority,
        }, default=str).decode()

        try:
            from app.infrastructure.clients.redis import redis_client
            raw = getattr(redis_client, "_raw_client", None) or redis_client

            # Lower score = higher priority (ZADD).
            # Add timestamp для FIFO в одинаковом priority.
            import time as _time
            score = priority * 10**10 + int(_time.time() * 1000)

            key = f"priority_queue:{self._queue}"
            await raw.zadd(key, {payload: score})

            # Trim if over max_size (keep lowest scores = highest priority)
            current_size = await raw.zcard(key)
            if current_size > self._max_size:
                await raw.zremrangebyrank(key, self._max_size, -1)

            exchange.set_property("priority_enqueued_id", msg_id)
            exchange.set_property("priority_enqueued_score", score)
        except Exception as exc:
            exchange.fail(f"Priority enqueue failed: {exc}")
