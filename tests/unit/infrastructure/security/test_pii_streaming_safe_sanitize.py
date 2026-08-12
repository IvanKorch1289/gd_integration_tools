"""D-AUDIT-8601: regression-тест PII streaming fail-open logging (DOMAIN-P0-003).

Фикс: _safe_sanitize при ошибке sanitizer-а возвращает original text
(для stream integrity), НО логирует ERROR с exc_type/exc_msg/chunk_len
вместо silent swallow.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.infrastructure.security.pii_streaming import _safe_sanitize


class _FakeSanitizer:
    """Sanitizer-мок, всегда кидающий исключение."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    async def sanitize(self, text: str, entities: list[str] | None = None) -> Any:
        raise self._exc


@pytest.mark.asyncio
async def test_safe_sanitize_returns_original_on_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ошибка sanitizer-а → возвращается original text, но ERROR логируется."""
    san = _FakeSanitizer(ValueError("spaCy model not loaded"))
    text = "my email is alice@example.com and SSN 123-45-6789"

    with caplog.at_level("ERROR", logger="src.backend.infrastructure.security.pii_streaming"):
        result = await _safe_sanitize(san, text, entities=("EMAIL", "SSN"))

    # backward-compat: original text возвращается (stream integrity)
    assert result == text
    # observability: ERROR залогирован с structured context
    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(error_records) == 1, f"Expected 1 ERROR, got: {error_records}"
    msg = error_records[0].message
    assert "PII LEAK POSSIBLE" in msg
    assert "ValueError" in msg
    assert "spaCy model not loaded" in msg
    assert "EMAIL" in msg
    assert "SSN" in msg


@pytest.mark.asyncio
async def test_safe_sanitize_passes_through_on_success() -> None:
    """Happy path: sanitizer.sanitize().sanitized_text возвращается."""
    fake_result = AsyncMock()
    fake_result.sanitized_text = "my email is [EMAIL_REDACTED]"
    san = AsyncMock()
    san.sanitize = AsyncMock(return_value=fake_result)

    result = await _safe_sanitize(san, "my email is alice@example.com", entities=None)
    assert result == "my email is [EMAIL_REDACTED]"


@pytest.mark.asyncio
async def test_safe_sanitize_catches_wide_exception_types(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Sanitizer может кинуть любой из ~10 типов (RuntimeError, ImportError,
    OSError, aiohttp.ClientError, ...) — все должны логироваться, не
    глотаться.
    """
    for exc in [
        RuntimeError("model load failed"),
        OSError("connection reset"),
        TimeoutError("ner inference timeout"),
        ImportError("spacy model missing"),
    ]:
        san = _FakeSanitizer(exc)
        caplog.clear()
        with caplog.at_level("ERROR", logger="src.backend.infrastructure.security.pii_streaming"):
            result = await _safe_sanitize(san, "test chunk", entities=None)
        assert result == "test chunk"  # original text returned
        assert any("PII LEAK POSSIBLE" in r.message for r in caplog.records), (
            f"Expected ERROR log for {type(exc).__name__}, "
            f"got: {[r.message for r in caplog.records]}"
        )
