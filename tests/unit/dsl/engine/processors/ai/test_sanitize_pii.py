"""Unit tests for SanitizePIIProcessor."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.backend.dsl.engine.processors.ai.sanitizepii_processor import SanitizePIIProcessor
from src.backend.dsl.engine.exchange import Exchange


class TestSanitizePIIProcessor:
    """Tests for SanitizePIIProcessor."""

    @pytest.mark.asyncio
    async def test_process_returns_empty_when_no_body(self) -> None:
        processor = SanitizePIIProcessor()
        exchange = MagicMock(spec=Exchange)
        exchange.in_message = MagicMock()
        exchange.in_message.body = None
        exchange.set_property = MagicMock()

        await processor.process(exchange, MagicMock())

        exchange.set_property.assert_called()

    @pytest.mark.asyncio
    async def test_process_returns_empty_when_no_text(self) -> None:
        processor = SanitizePIIProcessor()
        exchange = MagicMock(spec=Exchange)
        exchange.in_message = MagicMock()
        exchange.in_message.body = {}
        exchange.set_property = MagicMock()

        await processor.process(exchange, MagicMock())

        exchange.set_property.assert_called()

    def test_to_spec(self) -> None:
        processor = SanitizePIIProcessor()
        spec = processor.to_spec()
        assert spec is not None
        assert "sanitize_pii" in spec
