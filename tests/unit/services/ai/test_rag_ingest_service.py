"""Тесты RagIngestService: inline ingest + status tracking."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.backend.services.ai.rag_ingest_service import RagIngestService


@pytest.mark.asyncio
async def test_ingest_inline_processes_all_files() -> None:
    rag = type("R", (), {})()
    rag.ingest = AsyncMock(side_effect=["doc1", "doc2"])
    service = RagIngestService(rag_service=rag, deferred=False)

    result = await service.ingest(
        files=[("a.txt", b"hello"), ("b.txt", b"world")], collection="docs",
    )
    assert result["status"] == "completed"
    assert result["doc_ids"] == ["doc1", "doc2"]
    assert result["processed"] == 2
    assert rag.ingest.await_count == 2


@pytest.mark.asyncio
async def test_ingest_records_errors() -> None:
    rag = type("R", (), {})()
    rag.ingest = AsyncMock(side_effect=[RuntimeError("boom"), "doc-ok"])
    service = RagIngestService(rag_service=rag, deferred=False)

    result = await service.ingest(files=[("bad.txt", b"x"), ("good.txt", b"y")])
    assert result["status"] == "completed_with_errors"
    assert result["doc_ids"] == ["doc-ok"]
    assert result["errors"][0]["file"] == "bad.txt"


@pytest.mark.asyncio
async def test_status_returns_state() -> None:
    rag = type("R", (), {})()
    rag.ingest = AsyncMock(return_value="d")
    service = RagIngestService(rag_service=rag, deferred=False)
    started = await service.ingest(files=[("a.txt", b"x")])
    state = await service.status(started["task_id"])
    assert state is not None and state["status"] == "completed"


@pytest.mark.asyncio
async def test_status_returns_none_for_unknown_id() -> None:
    service = RagIngestService(rag_service=object())
    assert await service.status("missing") is None


@pytest.mark.asyncio
async def test_chunker_fingerprint_propagates_to_metadata() -> None:
    captured: list[dict] = []

    async def _capture(text, metadata=None, namespace="default"):
        captured.append(metadata or {})
        return "doc"

    rag = type("R", (), {})()
    rag.ingest = _capture
    service = RagIngestService(rag_service=rag, deferred=False)
    await service.ingest(files=[("x.txt", b"x")], collection="c1")
    assert "chunker_fingerprint" in captured[0]
    assert isinstance(captured[0]["chunker_fingerprint"], str)


@pytest.mark.asyncio
async def test_list_recent_returns_newest_first() -> None:
    rag = type("R", (), {})()
    rag.ingest = AsyncMock(return_value="d")
    service = RagIngestService(rag_service=rag, deferred=False)
    await service.ingest(files=[("a.txt", b"x")])
    await service.ingest(files=[("b.txt", b"y")])
    recent = await service.list_recent(limit=10)
    assert len(recent) == 2
    assert recent[0]["status"] == "completed"


# --- ingest_text (Sprint 2.2: single-doc для /ingest и /upload) ----------


@pytest.mark.asyncio
async def test_ingest_text_returns_single_doc_id() -> None:
    """ingest_text возвращает один doc_id (а не task_id dict)."""
    rag = type("R", (), {})()
    rag.ingest = AsyncMock(return_value="doc-sha256-abc")
    service = RagIngestService(rag_service=rag)

    doc_id = await service.ingest_text(
        content="hello world", namespace="ns1", metadata={"k": "v"}
    )
    assert doc_id == "doc-sha256-abc"
    rag.ingest.assert_awaited_once()
    # Namespace и metadata прокинуты в RAGService.ingest.
    call = rag.ingest.await_args
    assert call is not None
    assert call.kwargs["namespace"] == "ns1"
    assert call.kwargs["metadata"]["k"] == "v"


@pytest.mark.asyncio
async def test_ingest_text_accepts_bytes() -> None:
    """ingest_text принимает bytes (multipart upload) и декодирует в UTF-8."""
    captured: list[str] = []

    async def _capture(text: str, metadata=None, namespace: str = "default") -> str:
        captured.append(text)
        return "d"

    rag = type("R", (), {})()
    rag.ingest = _capture
    service = RagIngestService(rag_service=rag)

    await service.ingest_text(content="привет".encode("utf-8"))
    assert captured == ["привет"]


@pytest.mark.asyncio
async def test_ingest_text_propagates_filename_and_provenance() -> None:
    """ingest_text добавляет filename + chunker_fingerprint + embedding provenance."""
    captured: list[dict] = []

    async def _capture(text: str, metadata=None, namespace: str = "default") -> str:
        captured.append(metadata or {})
        return "d"

    rag = type("R", (), {})()
    rag.ingest = _capture
    service = RagIngestService(rag_service=rag)

    await service.ingest_text(
        content="text", filename="report.pdf", metadata={"source": "upload"}
    )
    md = captured[0]
    assert md["filename"] == "report.pdf"
    assert md["source"] == "upload"
    assert "chunker_fingerprint" in md
    assert isinstance(md["chunker_fingerprint"], str)


@pytest.mark.asyncio
async def test_ingest_text_masks_pii_when_flag_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sprint 2.2: при pii_mask_on_ingest=True single-doc ingest маскирует PII.

    Доказывает, что /ingest и /upload (через RagIngestService.ingest_text)
    проходят через тот же _maybe_mask_pii, что и bulk ingest.
    """
    import re
    from dataclasses import dataclass

    from src.backend.core.config import ai_stack
    from src.backend.core.di import providers

    @dataclass(slots=True)
    class _StubResult:
        sanitized_text: str
        replacements: dict[str, str]

    class _StubSanitizer:
        def sanitize_text(self, text: str) -> _StubResult:
            cleaned = re.sub(r"\d{3,}", "[REDACTED]", text)
            return _StubResult(
                sanitized_text=cleaned,
                replacements={"[REDACTED]": "***"} if cleaned != text else {},
            )

    monkeypatch.setattr(
        ai_stack.rag_ingest_settings, "pii_mask_on_ingest", True, raising=True
    )
    providers.set_ai_sanitizer_provider(_StubSanitizer())
    try:
        rag_mock = AsyncMock()
        rag_mock.ingest = AsyncMock(return_value="doc-1")
        svc = RagIngestService(rag_service=rag_mock)

        doc_id = await svc.ingest_text(
            content="ИНН 7707083893, договор 12345", namespace="ns1"
        )
        assert doc_id == "doc-1"

        call = rag_mock.ingest.await_args
        assert call is not None
        text_arg = call.args[0]
        metadata = call.kwargs["metadata"]

        # PII замаскирован в тексте, попавшем в RAG.
        assert "7707083893" not in text_arg
        assert "12345" not in text_arg
        assert "[REDACTED]" in text_arg

        # Metadata указывает на маскирование.
        assert metadata["pii_masked"] is True
        assert metadata["pii_masker_version"] == "_StubSanitizer"
    finally:
        providers.ai._overrides.pop("ai_sanitizer", None)


@pytest.mark.asyncio
async def test_ingest_text_passthrough_when_flag_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При pii_mask_on_ingest=False текст идёт в RAG как есть + pii_masked=False."""
    from src.backend.core.config import ai_stack

    monkeypatch.setattr(
        ai_stack.rag_ingest_settings, "pii_mask_on_ingest", False, raising=True
    )
    rag_mock = AsyncMock()
    rag_mock.ingest = AsyncMock(return_value="doc-1")
    svc = RagIngestService(rag_service=rag_mock)

    await svc.ingest_text(content="ИНН 7707083893", namespace="ns1")
    call = rag_mock.ingest.await_args
    assert call is not None
    text_arg = call.args[0]
    metadata = call.kwargs["metadata"]
    assert text_arg == "ИНН 7707083893"
    assert metadata["pii_masked"] is False


@pytest.mark.asyncio
async def test_ingest_text_user_metadata_takes_precedence() -> None:
    """User-provided metadata перекрывает fingerprint/provenance (последний win)."""
    captured: list[dict] = []

    async def _capture(text: str, metadata=None, namespace: str = "default") -> str:
        captured.append(metadata or {})
        return "d"

    rag = type("R", (), {})()
    rag.ingest = _capture
    service = RagIngestService(rag_service=rag)

    await service.ingest_text(
        content="x", metadata={"chunker_fingerprint": "USER-OVERRIDE"}
    )
    # User metadata wins (override после fingerprint в merge).
    assert captured[0]["chunker_fingerprint"] == "USER-OVERRIDE"
