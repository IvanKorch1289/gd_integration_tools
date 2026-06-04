"""Unit test для Block 1.3 (gap-ai-1.3, ADR-0072).

Проверяет что :class:`RagIngestService` маскирует PII в содержимом
документов до записи в Qdrant при ``RagIngestSettings.pii_mask_on_ingest=True``.

Сценарии:
1. ``pii_mask_on_ingest=False`` (default) → текст идёт в RAG без изменений;
   ``metadata.pii_masked == False``.
2. ``pii_mask_on_ingest=True`` → текст маскируется через DI-sanitizer;
   ``metadata.pii_masked == True``, ``metadata.pii_masker_version`` указан.
3. sanitize_text exception → ingest не падает, metadata содержит
   ``pii_mask_error`` для observability.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock

import pytest


@dataclass(slots=True)
class _StubSanitizationResult:
    """Stub :class:`SanitizationResult`."""

    sanitized_text: str
    replacements: dict[str, str]


class _StubSanitizer:
    """In-memory sanitizer — маскирует цифры 3+ как [REDACTED]."""

    def sanitize_text(self, text: str) -> _StubSanitizationResult:
        import re

        cleaned = re.sub(r"\d{3,}", "[REDACTED]", text)
        return _StubSanitizationResult(
            sanitized_text=cleaned,
            replacements={"[REDACTED]": "***"} if cleaned != text else {},
        )


class _FailingSanitizer:
    """Sanitizer, бросающий исключение — для проверки graceful degradation."""

    def sanitize_text(self, text: str) -> _StubSanitizationResult:
        raise RuntimeError("simulated sanitizer failure")


@pytest.mark.asyncio
async def test_ingest_passthrough_when_flag_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При pii_mask_on_ingest=False текст идёт в rag.ingest без маскирования."""
    from src.backend.core.config import ai_2026
    from src.backend.services.ai.rag_ingest_service import RagIngestService

    monkeypatch.setattr(
        ai_2026.rag_ingest_settings, "pii_mask_on_ingest", False, raising=True
    )

    rag_mock = AsyncMock()
    rag_mock.ingest = AsyncMock(return_value="doc-1")
    svc = RagIngestService(rag_service=rag_mock)

    await svc.ingest([("file.txt", "ИНН 7707083893".encode("utf-8"))], collection="ns")
    call = rag_mock.ingest.await_args
    assert call is not None
    text_arg = call.args[0]
    metadata = call.kwargs["metadata"]
    assert text_arg == "ИНН 7707083893"
    assert metadata["pii_masked"] is False


@pytest.mark.asyncio
async def test_ingest_masks_pii_when_flag_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """При pii_mask_on_ingest=True текст маскируется + metadata указывает версию sanitizer."""
    from src.backend.core.config import ai_2026
    from src.backend.core.di import providers
    from src.backend.services.ai.rag_ingest_service import RagIngestService

    monkeypatch.setattr(
        ai_2026.rag_ingest_settings, "pii_mask_on_ingest", True, raising=True
    )
    providers.set_ai_sanitizer_provider(_StubSanitizer())
    try:
        rag_mock = AsyncMock()
        rag_mock.ingest = AsyncMock(return_value="doc-1")
        svc = RagIngestService(rag_service=rag_mock)

        await svc.ingest(
            [("file.txt", "ИНН 7707083893, договор 12345".encode("utf-8"))],
            collection="ns",
        )
        call = rag_mock.ingest.await_args
        assert call is not None
        text_arg = call.args[0]
        metadata = call.kwargs["metadata"]

        # PII замаскирован.
        assert "7707083893" not in text_arg
        assert "12345" not in text_arg
        assert "[REDACTED]" in text_arg

        # Metadata содержит provenance.
        assert metadata["pii_masked"] is True
        assert metadata["pii_masker_version"] == "_StubSanitizer"
    finally:
        providers.ai._overrides.pop("ai_sanitizer", None)


@pytest.mark.asyncio
async def test_ingest_graceful_on_sanitizer_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При sanitize_text exception ingest продолжается + metadata содержит pii_mask_error."""
    from src.backend.core.config import ai_2026
    from src.backend.core.di import providers
    from src.backend.services.ai.rag_ingest_service import RagIngestService

    monkeypatch.setattr(
        ai_2026.rag_ingest_settings, "pii_mask_on_ingest", True, raising=True
    )
    providers.set_ai_sanitizer_provider(_FailingSanitizer())
    try:
        rag_mock = AsyncMock()
        rag_mock.ingest = AsyncMock(return_value="doc-1")
        svc = RagIngestService(rag_service=rag_mock)

        await svc.ingest([("file.txt", b"some text")], collection="ns")
        call = rag_mock.ingest.await_args
        assert call is not None
        metadata = call.kwargs["metadata"]
        # Graceful: ingest продолжился, текст не изменился, metadata содержит error.
        assert metadata["pii_masked"] is False
        assert "pii_mask_error" in metadata
        assert "simulated sanitizer failure" in metadata["pii_mask_error"]
    finally:
        providers.ai._overrides.pop("ai_sanitizer", None)
