"""Unit tests for RPA system processors."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.backend.dsl.engine.processors.rpa.system import (
    ShellExecProcessor,
    EmailComposeProcessor,
)
from src.backend.dsl.engine.exchange import Exchange


class TestShellExecProcessor:
    """Tests for ShellExecProcessor."""

    @pytest.mark.asyncio
    async def test_process_executes_shell(self) -> None:
        processor = ShellExecProcessor(command="echo hello")
        exchange = MagicMock(spec=Exchange)
        exchange.set_property = MagicMock()

        with patch("asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_proc:
            mock_process = MagicMock()
            mock_process.communicate = AsyncMock(return_value=(b"hello\n", b""))
            mock_process.returncode = 0
            mock_proc.return_value = mock_process
            await processor.process(exchange, MagicMock())

        exchange.set_property.assert_called()


class TestEmailComposeProcessor:
    """Tests for EmailComposeProcessor."""

    @pytest.mark.asyncio
    async def test_process_composes_email(self) -> None:
        processor = EmailComposeProcessor(
            to="test@example.com",
            subject="Test",
            body="Hello"
        )
        exchange = MagicMock(spec=Exchange)
        exchange.set_property = MagicMock()

        await processor.process(exchange, MagicMock())

        exchange.set_property.assert_called()
