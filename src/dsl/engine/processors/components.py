"""Camel Component processors — source/sink for HTTP, DB, File, Timer, Polling.

These processors provide direct I/O capabilities within DSL pipelines,
equivalent to Apache Camel's Component model.
"""

import asyncio
import logging
from typing import Any, Callable

import orjson

from app.dsl.engine.context import ExecutionContext
from app.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from app.dsl.engine.processors.base import BaseProcessor

__all__ = (
    "HttpCallProcessor",
    "DatabaseQueryProcessor",
    "FileReadProcessor",
    "FileWriteProcessor",
    "S3ReadProcessor",
    "S3WriteProcessor",
    "TimerProcessor",
    "PollingConsumerProcessor",
)

_comp_logger = logging.getLogger("dsl.components")


class HttpCallProcessor(BaseProcessor):
    """Camel HTTP Component — call external APIs from DSL pipeline.

    Supports GET/POST/PUT/DELETE with headers, auth, and timeout.
    """

    def __init__(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        auth_token: str | None = None,
        timeout: float = 30.0,
        body_from_exchange: bool = True,
        result_property: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"http:{method}:{url[:40]}")
        self._url = url
        self._method = method.upper()
        self._headers = headers or {}
        self._auth_token = auth_token
        self._timeout = timeout
        self._body_from_exchange = body_from_exchange
        self._result_property = result_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from app.infrastructure.clients.http import HttpClient

        client = HttpClient()

        json_body = None
        if self._method in ("POST", "PUT", "PATCH") and self._body_from_exchange:
            body = exchange.in_message.body
            if isinstance(body, dict):
                json_body = body

        url = self._url
        if "{" in url and isinstance(exchange.in_message.body, dict):
            try:
                url = url.format(**exchange.in_message.body)
            except (KeyError, IndexError):
                pass

        try:
            result = await client.make_request(
                method=self._method,
                url=url,
                headers=self._headers or None,
                json=json_body,
                auth_token=self._auth_token,
                total_timeout=self._timeout,
            )

            if self._result_property:
                exchange.set_property(self._result_property, result)
            exchange.set_out(body=result, headers=dict(exchange.in_message.headers))

        except Exception as exc:
            exchange.fail(f"HTTP {self._method} {url} failed: {exc}")


class DatabaseQueryProcessor(BaseProcessor):
    """Camel JDBC Component — query/execute SQL from DSL pipeline.

    Uses the application's async database engine.
    """

    def __init__(
        self,
        sql: str,
        *,
        params_from_body: bool = True,
        result_property: str = "db_result",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"db_query:{sql[:30]}")
        self._sql = sql
        self._params_from_body = params_from_body
        self._result_property = result_property

    _FORBIDDEN_SQL = {"DROP", "ALTER", "TRUNCATE", "CREATE", "GRANT", "REVOKE"}

    @staticmethod
    def _validate_sql(sql: str) -> None:
        """Block dangerous SQL: multi-statement, DDL, privilege commands."""
        stripped = sql.strip().rstrip(";")
        if ";" in stripped:
            raise ValueError("Multi-statement SQL is not allowed")
        first_word = stripped.split()[0].upper() if stripped else ""
        if first_word in DatabaseQueryProcessor._FORBIDDEN_SQL:
            raise ValueError(f"SQL command '{first_word}' is not allowed")

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from sqlalchemy import text

        from app.infrastructure.database.database import get_db_manager

        try:
            self._validate_sql(self._sql)
        except ValueError as exc:
            exchange.fail(f"SQL validation failed: {exc}")
            return

        params = {}
        if self._params_from_body:
            body = exchange.in_message.body
            if isinstance(body, dict):
                params = body

        try:
            db = get_db_manager()
            engine = db.get_async_engine()
            async with engine.connect() as conn:
                result = await conn.execute(text(self._sql), params)

                if self._sql.strip().upper().startswith("SELECT"):
                    rows = [dict(row._mapping) for row in result.fetchall()]
                    exchange.set_property(self._result_property, rows)
                    exchange.set_out(body=rows, headers=dict(exchange.in_message.headers))
                else:
                    await conn.commit()
                    exchange.set_property(self._result_property, {"rowcount": result.rowcount})

        except Exception as exc:
            exchange.fail(f"Database query failed: {exc}")


class FileReadProcessor(BaseProcessor):
    """Camel File Component (read) — read local file into exchange body."""

    def __init__(
        self,
        path: str | None = None,
        *,
        path_property: str | None = None,
        encoding: str = "utf-8",
        binary: bool = False,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"read_file:{path or 'dynamic'}")
        self._path = path
        self._path_property = path_property
        self._encoding = encoding
        self._binary = binary

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        import aiofiles

        path = self._path
        if self._path_property:
            path = exchange.properties.get(self._path_property, path)
        if not path:
            body = exchange.in_message.body
            path = body.get("path") if isinstance(body, dict) else str(body)

        if not path:
            exchange.fail("No file path provided")
            return

        try:
            if self._binary:
                async with aiofiles.open(path, "rb") as f:
                    data = await f.read()
            else:
                async with aiofiles.open(path, "r", encoding=self._encoding) as f:
                    data = await f.read()

            exchange.set_out(body=data, headers=dict(exchange.in_message.headers))
            exchange.in_message.set_header("CamelFileName", path)

        except (FileNotFoundError, PermissionError, OSError) as exc:
            exchange.fail(f"File read failed: {exc}")


class FileWriteProcessor(BaseProcessor):
    """Camel File Component (write) — write exchange body to local file."""

    def __init__(
        self,
        path: str | None = None,
        *,
        path_property: str | None = None,
        format: str = "auto",
        encoding: str = "utf-8",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"write_file:{path or 'dynamic'}")
        self._path = path
        self._path_property = path_property
        self._format = format
        self._encoding = encoding

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        import aiofiles

        path = self._path
        if self._path_property:
            path = exchange.properties.get(self._path_property, path)

        if not path:
            exchange.fail("No file path provided for write")
            return

        body = exchange.in_message.body
        fmt = self._format

        if fmt == "auto":
            if path.endswith(".json"):
                fmt = "json"
            elif path.endswith(".csv"):
                fmt = "csv"
            else:
                fmt = "text"

        try:
            if fmt == "json":
                content = orjson.dumps(body, default=str, option=orjson.OPT_INDENT_2)
                async with aiofiles.open(path, "wb") as f:
                    await f.write(content)
            elif fmt == "csv" and isinstance(body, list) and body and isinstance(body[0], dict):
                import csv
                import io
                buf = io.StringIO()
                writer = csv.DictWriter(buf, fieldnames=body[0].keys())
                writer.writeheader()
                writer.writerows(body)
                async with aiofiles.open(path, "w", encoding=self._encoding) as f:
                    await f.write(buf.getvalue())
            elif isinstance(body, bytes):
                async with aiofiles.open(path, "wb") as f:
                    await f.write(body)
            else:
                async with aiofiles.open(path, "w", encoding=self._encoding) as f:
                    await f.write(str(body))

            exchange.set_property("file_written", path)
            exchange.in_message.set_header("CamelFileName", path)

        except (PermissionError, OSError) as exc:
            exchange.fail(f"File write failed: {exc}")


class S3ReadProcessor(BaseProcessor):
    """Camel S3 Component (read) — download object from S3."""

    def __init__(
        self,
        bucket: str | None = None,
        key: str | None = None,
        *,
        key_property: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"s3_read:{bucket}/{key or 'dynamic'}")
        self._bucket = bucket
        self._key = key
        self._key_property = key_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from app.infrastructure.clients.storage import storage_client

        key = self._key
        if self._key_property:
            key = exchange.properties.get(self._key_property, key)
        if not key:
            body = exchange.in_message.body
            key = body.get("key") if isinstance(body, dict) else None

        if not key:
            exchange.fail("No S3 key provided")
            return

        try:
            data = await storage_client.download_file(key)
            exchange.set_out(body=data, headers=dict(exchange.in_message.headers))
            exchange.in_message.set_header("CamelS3Key", key)
        except Exception as exc:
            exchange.fail(f"S3 read failed: {exc}")


class S3WriteProcessor(BaseProcessor):
    """Camel S3 Component (write) — upload exchange body to S3."""

    def __init__(
        self,
        bucket: str | None = None,
        key: str | None = None,
        *,
        key_property: str | None = None,
        content_type: str = "application/octet-stream",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"s3_write:{bucket}/{key or 'dynamic'}")
        self._bucket = bucket
        self._key = key
        self._key_property = key_property
        self._content_type = content_type

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from app.infrastructure.clients.storage import storage_client

        key = self._key
        if self._key_property:
            key = exchange.properties.get(self._key_property, key)

        if not key:
            exchange.fail("No S3 key provided for write")
            return

        body = exchange.in_message.body
        if isinstance(body, str):
            data = body.encode("utf-8")
        elif isinstance(body, bytes):
            data = body
        else:
            data = orjson.dumps(body, default=str)

        try:
            await storage_client.upload_file(data, key, content_type=self._content_type)
            exchange.set_property("s3_written", key)
            exchange.in_message.set_header("CamelS3Key", key)
        except Exception as exc:
            exchange.fail(f"S3 write failed: {exc}")


class TimerProcessor(BaseProcessor):
    """Camel Timer Component — generates exchange events on interval or cron.

    When used as the first processor in a route, it acts as a source
    that triggers the pipeline periodically.
    """

    def __init__(
        self,
        *,
        interval_seconds: float | None = None,
        cron: str | None = None,
        max_fires: int | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"timer({interval_seconds or cron})")
        self._interval = interval_seconds
        self._cron = cron
        self._max_fires = max_fires
        self._fire_count = 0

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        import time

        self._fire_count += 1
        exchange.set_property("timer_fire_count", self._fire_count)
        exchange.set_property("timer_fired_at", time.time())

        if self._max_fires and self._fire_count >= self._max_fires:
            exchange.set_property("timer_exhausted", True)

        if exchange.in_message.body is None:
            exchange.in_message.body = {
                "timer_fire_count": self._fire_count,
                "timestamp": time.time(),
            }


class PollingConsumerProcessor(BaseProcessor):
    """Camel Polling Consumer — periodically calls an action and feeds results into pipeline."""

    def __init__(
        self,
        source_action: str,
        *,
        payload: dict[str, Any] | None = None,
        filter_fn: Callable[[Any], bool] | None = None,
        result_property: str = "polled_data",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"poll:{source_action}")
        self._action = source_action
        self._payload = payload or {}
        self._filter_fn = filter_fn
        self._result_property = result_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from app.schemas.invocation import ActionCommandSchema

        command = ActionCommandSchema(action=self._action, payload=self._payload)
        try:
            result = await context.action_registry.dispatch(command)
        except (KeyError, Exception) as exc:
            exchange.fail(f"Polling action '{self._action}' failed: {exc}")
            return

        if self._filter_fn and isinstance(result, list):
            result = [item for item in result if self._filter_fn(item)]

        exchange.set_property(self._result_property, result)
        exchange.set_out(body=result, headers=dict(exchange.in_message.headers))
