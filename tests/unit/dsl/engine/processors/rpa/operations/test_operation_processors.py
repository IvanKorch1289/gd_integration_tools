"""Unit tests for RPA operation processors."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.backend.dsl.engine.processors.rpa.operations.filemoveprocessor import FileMoveProcessor
from src.backend.dsl.engine.processors.rpa.operations.regexprocessor import RegexProcessor
from src.backend.dsl.engine.processors.rpa.operations.templaterenderprocessor import TemplateRenderProcessor
from src.backend.dsl.engine.processors.rpa.operations.hashprocessor import HashProcessor
from src.backend.dsl.engine.processors.rpa.operations.encryptprocessor import EncryptProcessor
from src.backend.dsl.engine.processors.rpa.operations.decryptprocessor import DecryptProcessor
from src.backend.dsl.engine.exchange import Exchange


class TestFileMoveProcessor:
    """Tests for FileMoveProcessor."""

    @pytest.mark.asyncio
    async def test_process_moves_file(self) -> None:
        # S164 W1: updated to match actual FileMoveProcessor API (src/dst/mode).
        processor = FileMoveProcessor(src="a.txt", dst="b.txt", mode="move")
        exchange = MagicMock(spec=Exchange)
        exchange.in_message = MagicMock()
        exchange.in_message.body = None  # параметры переданы в __init__
        exchange.set_property = MagicMock()

        with patch("shutil.move") as mock_move:
            await processor.process(exchange, MagicMock())
            mock_move.assert_called_once()

        exchange.set_property.assert_called()


class TestRegexProcessor:
    """Tests for RegexProcessor."""

    @pytest.mark.asyncio
    async def test_process_extracts_regex(self) -> None:
        processor = RegexProcessor(pattern=r"\d+", source="body", target="result")
        exchange = MagicMock(spec=Exchange)
        exchange.in_message = MagicMock()
        exchange.in_message.body = "abc123def456"
        exchange.set_property = MagicMock()

        await processor.process(exchange, MagicMock())

        exchange.set_property.assert_called()


class TestTemplateRenderProcessor:
    """Tests for TemplateRenderProcessor."""

    @pytest.mark.asyncio
    async def test_process_renders_template(self) -> None:
        processor = TemplateRenderProcessor(template="Hello {{ name }}")
        exchange = MagicMock(spec=Exchange)
        exchange.in_message = MagicMock()
        exchange.in_message.body = {"name": "World"}
        exchange.set_property = MagicMock()

        await processor.process(exchange, MagicMock())

        exchange.set_property.assert_called()


class TestHashProcessor:
    """Tests for HashProcessor."""

    @pytest.mark.asyncio
    async def test_process_hashes_data(self) -> None:
        processor = HashProcessor(algorithm="sha256", source="body", target="hash")
        exchange = MagicMock(spec=Exchange)
        exchange.in_message = MagicMock()
        exchange.in_message.body = b"test data"
        exchange.set_property = MagicMock()

        await processor.process(exchange, MagicMock())

        exchange.set_property.assert_called()


class TestEncryptProcessor:
    """Tests for EncryptProcessor."""

    @pytest.mark.asyncio
    async def test_process_encrypts_data(self) -> None:
        processor = EncryptProcessor(key="secret-key-1234567890123456", source="body", target="encrypted")
        exchange = MagicMock(spec=Exchange)
        exchange.in_message = MagicMock()
        exchange.in_message.body = "sensitive data"
        exchange.set_property = MagicMock()

        with patch("cryptography.fernet.Fernet") as mock_fernet:
            mock_instance = MagicMock()
            mock_instance.encrypt.return_value = b"encrypted"
            mock_fernet.return_value = mock_instance
            await processor.process(exchange, MagicMock())

        exchange.set_property.assert_called()


class TestDecryptProcessor:
    """Tests for DecryptProcessor."""

    @pytest.mark.asyncio
    async def test_process_decrypts_data(self) -> None:
        processor = DecryptProcessor(key="secret-key-1234567890123456", source="body", target="decrypted")
        exchange = MagicMock(spec=Exchange)
        exchange.in_message = MagicMock()
        exchange.in_message.body = b"encrypted data"
        exchange.set_property = MagicMock()

        with patch("cryptography.fernet.Fernet") as mock_fernet:
            mock_instance = MagicMock()
            mock_instance.decrypt.return_value = b"decrypted"
            mock_fernet.return_value = mock_instance
            await processor.process(exchange, MagicMock())

        exchange.set_property.assert_called()
