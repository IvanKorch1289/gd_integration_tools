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
        # S164 W1: updated to match actual ShellExecProcessor API.
        processor = ShellExecProcessor(command="echo", allowed_commands=["echo"])
        exchange = MagicMock(spec=Exchange)
        exchange.in_message = MagicMock()
        exchange.in_message.body = "hello"
        exchange.set_property = MagicMock()

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
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
        # S164 W1: updated to match actual EmailComposeProcessor API
        # (uses body_template, не body). Mock smtp_client to avoid
        # network dependency в test environment.
        from src.backend.infrastructure.clients.transport import smtp as smtp_mod

        processor = EmailComposeProcessor(
            to="test@example.com",
            subject="Test",
            body_template="Hello {name}",
        )
        exchange = MagicMock(spec=Exchange)
        exchange.in_message = MagicMock()
        exchange.in_message.body = {"name": "World"}
        exchange.set_property = MagicMock()

        with patch.object(smtp_mod, "smtp_client") as mock_smtp:
            mock_smtp.send_email = AsyncMock()
            await processor.process(exchange, MagicMock())

        exchange.set_property.assert_called()
