"""Unit-тесты CDCCaptureProcessor — Wave [wave:6.2/cdc-capture-processor]."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.processors.cdc_capture import (
    _ALLOWED_STRATEGIES,
    CDCCaptureProcessor,
)

# --------------------------------------------------------------------------- #
# Stubs (matching pattern from test_ai_processors_unit.py)
# --------------------------------------------------------------------------- #


class _Message:
    """Minimal Message stub matching the Message interface used by processors."""

    def __init__(self, body: Any = None) -> None:
        self.body = body
        self.headers: dict[str, Any] = {}


class _Exchange:
    """Minimal exchange stub: only properties dict + in_message body."""

    def __init__(self, properties: dict[str, Any] | None = None) -> None:
        self.properties = properties or {}
        self.in_message = _Message()
        self.out_message: _Message | None = None

    def set_property(self, key: str, value: Any) -> None:
        self.properties[key] = value

    def set_out(self, body: Any = None, headers: dict[str, Any] | None = None) -> None:
        self.out_message = _Message(body=body)
        if headers:
            self.out_message.headers = headers


class _Context:
    """Stub ExecutionContext — processors don't use it directly in these tests."""


# --------------------------------------------------------------------------- #
# CDCCaptureProcessor init validation
# --------------------------------------------------------------------------- #


class TestCDCCaptureProcessorInit:
    """Tests for CDCCaptureProcessor initialization and validation."""

    def test_default_values(self) -> None:
        """Processor initializes with correct default values."""
        processor = CDCCaptureProcessor(profile="oracle_prod", tables=["orders"])
        assert processor._profile == "oracle_prod"
        assert processor._tables == ["orders"]
        assert processor._strategy == "polling"
        assert processor._result_property == "cdc_events"
        assert processor._interval == 5.0
        assert processor._timestamp_column == "updated_at"
        assert processor._batch_size == 100
        assert processor._channel is None
        assert processor._include_schema is True

    def test_custom_values(self) -> None:
        """Processor accepts custom values for all parameters."""
        processor = CDCCaptureProcessor(
            profile="postgres_prod",
            tables=["users", "orders"],
            strategy="listen_notify",
            result_property="my_cdc_events",
            interval=10.0,
            timestamp_column="created_at",
            batch_size=50,
            channel="my_channel",
            include_schema=False,
        )
        assert processor._profile == "postgres_prod"
        assert processor._tables == ["users", "orders"]
        assert processor._strategy == "listen_notify"
        assert processor._result_property == "my_cdc_events"
        assert processor._interval == 10.0
        assert processor._timestamp_column == "created_at"
        assert processor._batch_size == 50
        assert processor._channel == "my_channel"
        assert processor._include_schema is False

    def test_rejects_invalid_strategy(self) -> None:
        """Processor raises ValueError for invalid strategy."""
        with pytest.raises(ValueError, match="strategy must be one of"):
            CDCCaptureProcessor(
                profile="oracle_prod", tables=["orders"], strategy="invalid_strategy"
            )

    def test_rejects_empty_tables(self) -> None:
        """Processor raises ValueError when tables list is empty."""
        with pytest.raises(ValueError, match="tables cannot be empty"):
            CDCCaptureProcessor(profile="oracle_prod", tables=[])

    def test_name_auto_generated(self) -> None:
        """Processor auto-generates name from profile and strategy."""
        processor = CDCCaptureProcessor(profile="oracle_prod", tables=["orders"])
        assert processor.name == "cdc_capture:oracle_prod:polling"

    def test_name_custom(self) -> None:
        """Processor accepts custom name."""
        processor = CDCCaptureProcessor(
            profile="oracle_prod", tables=["orders"], name="my_custom_name"
        )
        assert processor.name == "my_custom_name"


# --------------------------------------------------------------------------- #
# CDCCaptureProcessor.to_spec
# --------------------------------------------------------------------------- #


class TestCDCCaptureProcessorToSpec:
    """Tests for CDCCaptureProcessor.to_spec()."""

    def test_to_spec_default(self) -> None:
        """to_spec returns correct spec with default values."""
        processor = CDCCaptureProcessor(profile="oracle_prod", tables=["orders"])
        spec = processor.to_spec()
        assert spec == {
            "cdc_capture": {
                "profile": "oracle_prod",
                "tables": ["orders"],
                "strategy": "polling",
            }
        }

    def test_to_spec_custom_values(self) -> None:
        """to_spec includes non-default values."""
        processor = CDCCaptureProcessor(
            profile="postgres_prod",
            tables=["users", "orders"],
            strategy="listen_notify",
            result_property="custom_events",
            interval=10.0,
            timestamp_column="created_at",
            batch_size=50,
            channel="my_channel",
            include_schema=False,
        )
        spec = processor.to_spec()
        assert spec["cdc_capture"]["profile"] == "postgres_prod"
        assert spec["cdc_capture"]["tables"] == ["users", "orders"]
        assert spec["cdc_capture"]["strategy"] == "listen_notify"
        assert spec["cdc_capture"]["result_property"] == "custom_events"
        assert spec["cdc_capture"]["interval"] == 10.0
        assert spec["cdc_capture"]["timestamp_column"] == "created_at"
        assert spec["cdc_capture"]["batch_size"] == 50
        assert spec["cdc_capture"]["channel"] == "my_channel"
        assert spec["cdc_capture"]["include_schema"] is False


# --------------------------------------------------------------------------- #
# CDCCaptureProcessor.process
# --------------------------------------------------------------------------- #


class TestCDCCaptureProcessorProcess:
    """Tests for CDCCaptureProcessor.process()."""

    @pytest.mark.asyncio
    async def test_process_subscribes_on_first_call(self) -> None:
        """Processor creates CDC subscription on first process call."""
        processor = CDCCaptureProcessor(
            profile="oracle_prod", tables=["orders"], strategy="polling"
        )

        mock_client = MagicMock()
        mock_client.subscribe = AsyncMock(return_value="sub_123")
        mock_exchange = _Exchange()

        with patch(
            "src.backend.dsl.engine.processors.cdc_capture.get_cdc_client",
            return_value=mock_client,
        ):
            await processor.process(mock_exchange, _Context())

        mock_client.subscribe.assert_called_once_with(
            profile="oracle_prod",
            tables=["orders"],
            strategy="polling",
            interval=5.0,
            timestamp_column="updated_at",
            batch_size=100,
            channel=None,
            callback=None,
            target_action=None,
        )
        assert processor._subscription_id == "sub_123"
        assert mock_exchange.properties["cdc_subscription_id"] == "sub_123"

    @pytest.mark.asyncio
    async def test_process_does_not_resubscribe(self) -> None:
        """Processor does not create new subscription on subsequent calls."""
        processor = CDCCaptureProcessor(
            profile="oracle_prod", tables=["orders"], strategy="polling"
        )
        processor._subscription_id = "existing_sub_456"

        mock_client = MagicMock()
        mock_client.subscribe = AsyncMock(return_value="new_sub")
        mock_exchange = _Exchange()

        with patch(
            "src.backend.dsl.engine.processors.cdc_capture.get_cdc_client",
            return_value=mock_client,
        ):
            await processor.process(mock_exchange, _Context())

        mock_client.subscribe.assert_not_called()
        assert mock_exchange.properties["cdc_subscription_id"] == "existing_sub_456"

    @pytest.mark.asyncio
    async def test_process_sets_result_property(self) -> None:
        """Processor sets result_property with subscription info."""
        processor = CDCCaptureProcessor(
            profile="oracle_prod",
            tables=["orders", "customers"],
            strategy="listen_notify",
            result_property="my_cdc_events",
        )

        mock_client = MagicMock()
        mock_client.subscribe = AsyncMock(return_value="sub_789")
        mock_exchange = _Exchange()

        with patch(
            "src.backend.dsl.engine.processors.cdc_capture.get_cdc_client",
            return_value=mock_client,
        ):
            await processor.process(mock_exchange, _Context())

        assert "my_cdc_events" in mock_exchange.properties
        result = mock_exchange.properties["my_cdc_events"]
        assert result["subscription_id"] == "sub_789"
        assert result["profile"] == "oracle_prod"
        assert result["tables"] == ["orders", "customers"]
        assert result["strategy"] == "listen_notify"
        assert result["status"] == "cdc_capture_active"

    @pytest.mark.asyncio
    async def test_process_sets_out_message(self) -> None:
        """Processor sets out_message with status info."""
        processor = CDCCaptureProcessor(
            profile="oracle_prod", tables=["orders"], strategy="polling"
        )

        mock_client = MagicMock()
        mock_client.subscribe = AsyncMock(return_value="sub_abc")
        mock_exchange = _Exchange()
        mock_exchange.in_message.headers = {"X-Request-ID": "req_123"}

        with patch(
            "src.backend.dsl.engine.processors.cdc_capture.get_cdc_client",
            return_value=mock_client,
        ):
            await processor.process(mock_exchange, _Context())

        assert mock_exchange.out_message is not None
        assert mock_exchange.out_message.body["status"] == "cdc_capture_active"
        assert mock_exchange.out_message.body["subscription_id"] == "sub_abc"
        assert mock_exchange.out_message.headers["X-Request-ID"] == "req_123"


# --------------------------------------------------------------------------- #
# Module-level constants
# --------------------------------------------------------------------------- #


def test_allowed_strategies() -> None:
    """Module defines correct allowed strategies."""
    assert _ALLOWED_STRATEGIES == {"polling", "listen_notify", "logminer"}
