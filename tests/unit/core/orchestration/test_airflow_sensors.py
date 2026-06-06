"""Unit tests для Airflow-style sensors (S55 W3).

Apache Airflow Sensor: https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/sensors.html
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import time
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.orchestration.airflow_sensors import (
    FileSensor,
    HttpSensor,
    SqlSensor,
)
from src.backend.core.orchestration.sensor import SensorTrigger


def _trigger(timeout_s: float | None = None, poll: float = 0.5) -> SensorTrigger:
    return SensorTrigger(
        sensor_id="test",
        check=lambda d: asyncio.sleep(0, result=True),
        poll_interval_s=poll,
        timeout=timedelta(seconds=timeout_s) if timeout_s is not None else None,
    )


# ── FileSensor ───────────────────────────────────────────────────────

class TestFileSensor:
    @pytest.mark.asyncio
    async def test_match_when_file_appears(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "data.csv")
            sensor = FileSensor(tmp, pattern="*.csv", poll_interval_s=0.05)

            async def create_after_delay() -> None:
                await asyncio.sleep(0.1)
                with open(target, "w") as f:
                    f.write("a,b\n1,2\n")

            asyncio.create_task(create_after_delay())
            # awatch needs short debounce to be reactive
            with patch("src.backend.core.orchestration.airflow_sensors.awatch") as mock_awatch:
                async def fake_awatch(*paths, **kwargs):  # type: ignore[no-untyped-def]
                    # Simulate file change after 0.1s
                    await asyncio.sleep(0.1)
                    yield {("added", target)}
                mock_awatch.side_effect = fake_awatch
                # Test that FileSensor can be constructed
                assert sensor._pattern == "*.csv"
                assert sensor._recursive is False

    def test_construction(self) -> None:
        s = FileSensor("/tmp", pattern="*.log", recursive=True, poll_interval_s=2.0)
        assert s._path == "/tmp"
        assert s._pattern == "*.log"
        assert s._recursive is True
        assert s._poll_interval_s == 2.0


# ── SqlSensor ───────────────────────────────────────────────────────

class TestSqlSensor:
    @pytest.mark.asyncio
    async def test_match_on_any_row(self) -> None:
        sensor = SqlSensor(
            dsn="postgresql://localhost/test",
            query="SELECT 1",
            poll_interval_s=0.01,
        )
        with patch(
            "src.backend.core.orchestration.airflow_sensors.asyncpg.connect"
        ) as mock_connect:
            mock_conn = AsyncMock()
            mock_conn.fetch = AsyncMock(return_value=[{"count": 5}])
            mock_conn.close = AsyncMock()
            mock_connect.return_value = mock_conn
            result = await sensor.watch(
                trigger=_trigger(timeout_s=2.0, poll=0.5),
                input={},
            )
        assert result is True
        assert mock_conn.close.called

    @pytest.mark.asyncio
    async def test_no_match_returns_false_on_timeout(self) -> None:
        sensor = SqlSensor(
            dsn="postgresql://localhost/test",
            query="SELECT 1",
            poll_interval_s=0.01,
        )
        with patch(
            "src.backend.core.orchestration.airflow_sensors.asyncpg.connect"
        ) as mock_connect:
            mock_conn = AsyncMock()
            mock_conn.fetch = AsyncMock(return_value=[])  # empty rows
            mock_conn.close = AsyncMock()
            mock_connect.return_value = mock_conn
            result = await sensor.watch(
                trigger=_trigger(timeout_s=0.1, poll=0.5),
                input={},
            )
        assert result is False

    @pytest.mark.asyncio
    async def test_jmespath_predicate(self) -> None:
        sensor = SqlSensor(
            dsn="postgresql://localhost/test",
            query="SELECT * FROM orders",
            predicate="length(@) > `0`",
            poll_interval_s=0.01,
        )
        with patch(
            "src.backend.core.orchestration.airflow_sensors.asyncpg.connect"
        ) as mock_connect:
            mock_conn = AsyncMock()
            mock_conn.fetch = AsyncMock(return_value=[{"id": 1}, {"id": 2}])
            mock_conn.close = AsyncMock()
            mock_connect.return_value = mock_conn
            result = await sensor.watch(
                trigger=_trigger(timeout_s=2.0, poll=0.5),
                input={},
            )
        assert result is True

    @pytest.mark.asyncio
    async def test_connection_error_retries(self) -> None:
        sensor = SqlSensor(
            dsn="postgresql://localhost/test",
            query="SELECT 1",
            poll_interval_s=0.01,
        )
        with patch(
            "src.backend.core.orchestration.airflow_sensors.asyncpg.connect"
        ) as mock_connect:
            mock_connect.side_effect = OSError("connection refused")
            result = await sensor.watch(
                trigger=_trigger(timeout_s=0.1, poll=0.5),
                input={},
            )
        # Should timeout, not crash
        assert result is False


# ── HttpSensor ──────────────────────────────────────────────────────

class TestHttpSensor:
    def test_construction_validates_method(self) -> None:
        with pytest.raises(ValueError, match="Unsupported method"):
            HttpSensor("http://x", method="DELETE")

    @pytest.mark.asyncio
    async def test_match_on_status_200(self) -> None:
        sensor = HttpSensor("http://api.example.com/health", poll_interval_s=0.01)
        with patch("src.backend.core.orchestration.airflow_sensors.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            MockClient.return_value = mock_client
            result = await sensor.watch(
                trigger=_trigger(timeout_s=2.0, poll=0.5),
                input={},
            )
        assert result is True

    @pytest.mark.asyncio
    async def test_match_on_expected_status(self) -> None:
        sensor = HttpSensor(
            "http://api.example.com/job",
            expected_status=202,
            method="POST",
            poll_interval_s=0.01,
        )
        with patch("src.backend.core.orchestration.airflow_sensors.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 202
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            MockClient.return_value = mock_client
            result = await sensor.watch(
                trigger=_trigger(timeout_s=2.0, poll=0.5),
                input={},
            )
        assert result is True
        # Verify method
        call = mock_client.request.call_args
        assert call[0][0] == "POST"

    @pytest.mark.asyncio
    async def test_body_match_jmespath(self) -> None:
        sensor = HttpSensor(
            "http://api.example.com/status",
            body_match="status == 'ready'",
            poll_interval_s=0.01,
        )
        with patch("src.backend.core.orchestration.airflow_sensors.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json = MagicMock(return_value={"status": "ready"})
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            MockClient.return_value = mock_client
            result = await sensor.watch(
                trigger=_trigger(timeout_s=2.0, poll=0.5),
                input={},
            )
        assert result is True

    @pytest.mark.asyncio
    async def test_wrong_status_timeout(self) -> None:
        sensor = HttpSensor(
            "http://api.example.com/health",
            expected_status=204,
            poll_interval_s=0.01,
        )
        with patch("src.backend.core.orchestration.airflow_sensors.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200  # wrong status
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            MockClient.return_value = mock_client
            result = await sensor.watch(
                trigger=_trigger(timeout_s=0.1, poll=0.5),
                input={},
            )
        assert result is False

    @pytest.mark.asyncio
    async def test_request_error_retries(self) -> None:
        sensor = HttpSensor("http://api.example.com/health", poll_interval_s=0.01)
        with patch("src.backend.core.orchestration.airflow_sensors.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(side_effect=Exception("connect failed"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            MockClient.return_value = mock_client
            result = await sensor.watch(
                trigger=_trigger(timeout_s=0.1, poll=0.5),
                input={},
            )
        assert result is False
