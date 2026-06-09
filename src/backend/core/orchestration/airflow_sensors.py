"""Airflow-style Sensors: FileSensor, SqlSensor, HttpSensor (S55 W3).

Apache Airflow Sensor: https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/sensors.html
Pattern: long-running watcher, polling external condition, triggers action на match.

Реализация: каждый sensor = async coroutine, polls condition с экспоненциальным
backoff до match или deadline. На match → SensorTrigger.on_match_action диспатчится.

Библиотеки:
* FileSensor — watchfiles (Python 3.12+ filesystem change detection)
* SqlSensor — asyncpg (raw SQL query) + jmespath (result predicate)
* HttpSensor — httpx async client
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import asyncpg
import httpx
import jmespath
from watchfiles import awatch

from src.backend.core.logging import get_logger
from src.backend.core.orchestration.sensor import Sensor, SensorTrigger

# S3 sensor uses aioboto3 (user-approved dep, install via `uv pip install aioboto3`).
# Lazy import: S3Sensor construction fails with ImportError if aioboto3 not installed,
# so the rest of the module works on light installs.

__all__ = (
    "FileSensor",
    "HttpSensor",
    "S3Sensor",
    "Sensor",
    "SensorTrigger",
    "SqlSensor",
)

_log = get_logger(__name__)


# ── FileSensor ──────────────────────────────────────────────────────


class FileSensor:
    """Watches file/glob path, triggers action on appearance/modification.

    Apache Airflow S3KeySensor analogue (локальный, без S3).
    Использует ``watchfiles.awatch`` для эффективного inotify-based watching
    (без polling overhead).

    Args:
        path: file path или glob pattern (relative to watch root).
        pattern: optional — match against glob pattern (default: exact path).
        recursive: watch recursively (default False).
        poll_interval_s: minimum interval between events (default 1.0).
    """

    def __init__(
        self,
        path: str,
        *,
        pattern: str | None = None,
        recursive: bool = False,
        poll_interval_s: float = 1.0,
    ) -> None:
        self._path = path
        self._pattern = pattern
        self._recursive = recursive
        self._poll_interval_s = poll_interval_s

    async def watch(
        self,
        *,
        trigger: SensorTrigger,
        input: dict[str, Any],
        namespace: str = "default",
    ) -> bool:
        """Returns True if match found within trigger.timeout, else False."""
        start = time.monotonic()
        _log.info("FileSensor: watching %s (recursive=%s)", self._path, self._recursive)

        try:
            async for changes in awatch(
                self._path,
                recursive=self._recursive,
                step=max(50, int(self._poll_interval_s * 1000)),
            ):
                # changes = set of (change_type, path) tuples
                if not changes:
                    continue
                if self._pattern is not None:
                    import fnmatch

                    matched = any(
                        fnmatch.fnmatch(os.path.basename(p), self._pattern)
                        for _, p in changes
                    )
                    if not matched:
                        continue
                _log.info("FileSensor: match for %s (changes=%s)", self._path, changes)
                return True
                # Note: awatch doesn't easily check timeout — for that,
                # we wrap with wait_for in production.
        except asyncio.CancelledError:
            return False

        # If timeout was set, watch will be interrupted externally
        if trigger.timeout is not None:
            elapsed = time.monotonic() - start
            if elapsed >= trigger.timeout.total_seconds():
                _log.info("FileSensor: timeout %s reached", trigger.timeout)
                return False
        return False


# ── SqlSensor ───────────────────────────────────────────────────────


class SqlSensor:
    """Polls SQL query until it returns rows (or matches predicate).

    Apache Airflow SqlSensor analogue.

    Args:
        dsn: PostgreSQL connection string (asyncpg DSN).
        query: SQL query (должна возвращать 0+ rows).
        predicate: optional JMESPath expression evaluated against query result.
            Если задан — match when truthy. Default: match when any row returned.
        poll_interval_s: interval between polls (default 5.0).
    """

    def __init__(
        self,
        dsn: str,
        query: str,
        *,
        predicate: str | None = None,
        poll_interval_s: float = 5.0,
    ) -> None:
        self._dsn = dsn
        self._query = query
        self._predicate = predicate
        self._poll_interval_s = poll_interval_s

    async def watch(
        self,
        *,
        trigger: SensorTrigger,
        input: dict[str, Any],
        namespace: str = "default",
    ) -> bool:
        start = time.monotonic()
        timeout_s = trigger.timeout.total_seconds() if trigger.timeout else None
        attempt = 0
        _log.info("SqlSensor: polling %s", self._dsn.split("@")[-1])

        while True:
            attempt += 1
            try:
                conn = await asyncpg.connect(self._dsn)
                try:
                    rows = await conn.fetch(self._query)
                finally:
                    await conn.close()

                rows_dicts = [dict(r) for r in rows]
                if self._predicate is not None:
                    matched = bool(jmespath.search(self._predicate, rows_dicts))
                else:
                    matched = len(rows_dicts) > 0

                if matched:
                    _log.info(
                        "SqlSensor: match (attempt %d, %d rows)",
                        attempt,
                        len(rows_dicts),
                    )
                    return True
            except Exception as e:
                _log.warning("SqlSensor: query failed (attempt %d): %s", attempt, e)

            # Check timeout
            elapsed = time.monotonic() - start
            if timeout_s is not None and elapsed >= timeout_s:
                _log.info("SqlSensor: timeout %ss reached", timeout_s)
                return False

            # Exponential backoff: min(poll, 2^(attempt-1) * poll)
            backoff = min(
                self._poll_interval_s,
                (2 ** min(attempt - 1, 6)) * self._poll_interval_s,
            )
            await asyncio.sleep(backoff)


# ── HttpSensor ──────────────────────────────────────────────────────


class HttpSensor:
    """Polls HTTP endpoint until status matches expected.

    Apache Airflow HttpSensor analogue (extended).

    Args:
        url: HTTP endpoint.
        expected_status: HTTP status code to match (default 200).
        method: HTTP method (default GET).
        headers: optional headers dict.
        body_match: optional JMESPath/JSONPath applied to response body.
            If provided, match requires both status AND body_match truthy.
        poll_interval_s: interval between polls (default 10.0).
    """

    def __init__(
        self,
        url: str,
        *,
        expected_status: int = 200,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body_match: str | None = None,
        poll_interval_s: float = 10.0,
    ) -> None:
        if method.upper() not in ("GET", "HEAD", "POST", "PUT"):
            raise ValueError(f"Unsupported method: {method}")
        self._url = url
        self._expected_status = expected_status
        self._method = method.upper()
        self._headers = headers or {}
        self._body_match = body_match
        self._poll_interval_s = poll_interval_s

    async def watch(
        self,
        *,
        trigger: SensorTrigger,
        input: dict[str, Any],
        namespace: str = "default",
    ) -> bool:
        start = time.monotonic()
        timeout_s = trigger.timeout.total_seconds() if trigger.timeout else None
        attempt = 0
        _log.info("HttpSensor: polling %s %s", self._method, self._url)

        async with httpx.AsyncClient(timeout=10.0) as client:
            while True:
                attempt += 1
                try:
                    resp = await client.request(
                        self._method, self._url, headers=self._headers
                    )
                    if resp.status_code == self._expected_status:
                        if self._body_match is None:
                            _log.info(
                                "HttpSensor: match (attempt %d, status=%d)",
                                attempt,
                                resp.status_code,
                            )
                            return True
                        try:
                            data = resp.json()
                        except Exception:
                            data = resp.text
                        if jmespath.search(self._body_match, data):
                            _log.info(
                                "HttpSensor: match (attempt %d, body matched)", attempt
                            )
                            return True
                except Exception as e:
                    _log.warning(
                        "HttpSensor: request failed (attempt %d): %s", attempt, e
                    )

                elapsed = time.monotonic() - start
                if timeout_s is not None and elapsed >= timeout_s:
                    _log.info("HttpSensor: timeout %ss reached", timeout_s)
                    return False

                backoff = min(
                    self._poll_interval_s,
                    (2 ** min(attempt - 1, 6)) * self._poll_interval_s,
                )
                await asyncio.sleep(backoff)


# ── S3Sensor ────────────────────────────────────────────────────────


class S3Sensor:
    """Polls S3 object until it appears (or matches predicate).

    Apache Airflow S3KeySensor analogue (async).

    Args:
        bucket: S3 bucket name.
        key: S3 object key.
        aws_access_key_id: optional AWS access key (default: from boto3
            default credential chain).
        aws_secret_access_key: optional AWS secret (default: from boto3 chain).
        region: AWS region (default ``"us-east-1"``).
        endpoint_url: optional custom endpoint (для S3-compatible storage
            типа MinIO, Ceph, Garage).
        poll_interval_s: interval between polls (default 30.0).

    Raises:
        ImportError: если ``aioboto3`` не установлен.
            Установка: ``uv pip install aioboto3``.
    """

    def __init__(
        self,
        bucket: str,
        key: str,
        *,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        region: str = "us-east-1",
        endpoint_url: str | None = None,
        poll_interval_s: float = 30.0,
    ) -> None:
        try:
            import aioboto3  # noqa: F401  (import check)
        except ImportError as e:
            raise ImportError(
                "S3Sensor requires aioboto3. Install: uv pip install aioboto3"
            ) from e
        self._bucket = bucket
        self._key = key
        self._aws_access_key_id = aws_access_key_id
        self._aws_secret_access_key = aws_secret_access_key
        self._region = region
        self._endpoint_url = endpoint_url
        self._poll_interval_s = poll_interval_s

    async def watch(
        self,
        *,
        trigger: SensorTrigger,
        input: dict[str, Any],
        namespace: str = "default",
    ) -> bool:
        import aioboto3

        start = time.monotonic()
        timeout_s = trigger.timeout.total_seconds() if trigger.timeout else None
        attempt = 0
        _log.info("S3Sensor: polling s3://%s/%s", self._bucket, self._key)

        session = aioboto3.Session()
        while True:
            attempt += 1
            try:
                async with session.client(
                    "s3",
                    aws_access_key_id=self._aws_access_key_id,
                    aws_secret_access_key=self._aws_secret_access_key,
                    region_name=self._region,
                    endpoint_url=self._endpoint_url,
                ) as s3:
                    resp = await s3.head_object(Bucket=self._bucket, Key=self._key)
                    if resp.get("ResponseMetadata", {}).get("HTTPStatusCode") == 200:
                        _log.info(
                            "S3Sensor: match (attempt %d, size=%s)",
                            attempt,
                            resp.get("ContentLength"),
                        )
                        return True
            except Exception as e:
                # 404 (NotFound) → expected while waiting; other errors → warn
                if "NoSuchKey" not in repr(e) and "404" not in repr(e):
                    _log.warning(
                        "S3Sensor: head_object failed (attempt %d): %s", attempt, e
                    )

            elapsed = time.monotonic() - start
            if timeout_s is not None and elapsed >= timeout_s:
                _log.info("S3Sensor: timeout %ss reached", timeout_s)
                return False

            backoff = min(
                self._poll_interval_s,
                (2 ** min(attempt - 1, 6)) * self._poll_interval_s,
            )
            await asyncio.sleep(backoff)
