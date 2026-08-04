"""Unit tests for RagIngestProcessor."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.dsl.engine.processors.ai.ragingest_processor import RagIngestProcessor


class _Message:
    def __init__(self, body: Any = None) -> None:
        self.body = body


class _Exchange:
    def __init__(
        self, body: Any = None, properties: dict[str, Any] | None = None
    ) -> None:
        self.in_message = _Message(body=body)
        self.properties: dict[str, Any] = properties or {}

    def set_property(self, key: str, value: Any) -> None:
        self.properties[key] = value

    def get_property(self, key: str, default: Any = None) -> Any:
        return self.properties.get(key, default)


class _Context:
    pass


class TestRagIngestProcessor:
    """Tests for :class:`RagIngestProcessor`."""

    @pytest.mark.asyncio
    async def test_ingests_from_in_message_body(self) -> None:
        exchange = _Exchange(body="document text")
        proc = RagIngestProcessor(collection="docs")

        # Round 7 Sprint 1.1 P0 fix: RagIngestProcessor теперь применяет
        # _maybe_mask_pii перед записью в vector store. Mock'аем sanitizer
        # в SOURCE-модуле (rag_ingest_service) — потому что processor импортит
        # helper через from-import внутри process(), что привязывает к
        # source module path.
        with (
            patch(
                "src.backend.services.ai.rag_service.get_rag_service"
            ) as mock_get,
            patch(
                "src.backend.services.ai.rag_ingest_service._maybe_mask_pii",
                return_value=("document text", {"pii_masked": False}),
            ),
        ):
            mock_rag = AsyncMock()
            mock_rag.ingest = AsyncMock(return_value="doc-id-1")
            mock_get.return_value = mock_rag

            await proc.process(exchange, _Context())

        mock_rag.ingest.assert_awaited_once_with(
            content="document text",
            metadata={
                "modal": "text",
                "collection": "docs",
                "pii_masked": False,
            },
            namespace="docs",
        )
        assert exchange.properties["ingest_doc_id"] == "doc-id-1"

    @pytest.mark.asyncio
    async def test_ingests_from_source_property(self) -> None:
        exchange = _Exchange()
        exchange.set_property("doc", "prop text")
        proc = RagIngestProcessor(source_property="doc", collection="c")

        with (
            patch(
                "src.backend.services.ai.rag_service.get_rag_service"
            ) as mock_get,
            patch(
                "src.backend.services.ai.rag_ingest_service._maybe_mask_pii",
                return_value=("prop text", {"pii_masked": False}),
            ),
        ):
            mock_rag = AsyncMock()
            mock_rag.ingest = AsyncMock(return_value="id-2")
            mock_get.return_value = mock_rag

            await proc.process(exchange, _Context())

        mock_rag.ingest.assert_awaited_once_with(
            content="prop text",
            metadata={
                "modal": "text",
                "collection": "c",
                "pii_masked": False,
            },
            namespace="c",
        )
        assert exchange.properties["ingest_doc_id"] == "id-2"

    @pytest.mark.asyncio
    async def test_empty_content_sets_none(self) -> None:
        exchange = _Exchange(body="")
        proc = RagIngestProcessor()

        with patch("src.backend.services.ai.rag_service.get_rag_service") as mock_get:
            await proc.process(exchange, _Context())

        mock_get.assert_not_called()
        assert exchange.properties["ingest_doc_id"] is None

    @pytest.mark.asyncio
    async def test_pii_masking_applied_to_content(self) -> None:
        """Round 7 Sprint 1.1 P0: PII в content маскируется перед ingest.

        Тест проверяет, что ``_maybe_mask_pii`` вызывается и его результат
        (masked text + pii_meta) пробрасывается в ``rag.ingest``. Реальный
        Presidio не запускаем (slow + требует модели) — мокаем helper.
        """
        exchange = _Exchange(body="John Doe SSN: 123-45-6789")
        proc = RagIngestProcessor(collection="sensitive")

        with (
            patch(
                "src.backend.services.ai.rag_service.get_rag_service"
            ) as mock_get,
            patch(
                "src.backend.services.ai.rag_ingest_service._maybe_mask_pii",
                return_value=(
                    "<PERSON> SSN: <US_SSN>",
                    {
                        "pii_masked": True,
                        "pii_masker_version": "TestSanitizer",
                    },
                ),
            ),
        ):
            mock_rag = AsyncMock()
            mock_rag.ingest = AsyncMock(return_value="masked-id")
            mock_get.return_value = mock_rag

            await proc.process(exchange, _Context())

        mock_rag.ingest.assert_awaited_once_with(
            content="<PERSON> SSN: <US_SSN>",
            metadata={
                "modal": "text",
                "collection": "sensitive",
                "pii_masked": True,
                "pii_masker_version": "TestSanitizer",
            },
            namespace="sensitive",
        )
        assert exchange.properties["ingest_doc_id"] == "masked-id"

    @pytest.mark.asyncio
    async def test_non_string_content_converted(self) -> None:
        exchange = _Exchange(body={"key": "val"})
        proc = RagIngestProcessor()

        with (
            patch(
                "src.backend.services.ai.rag_service.get_rag_service"
            ) as mock_get,
            patch(
                "src.backend.services.ai.rag_ingest_service._maybe_mask_pii",
                side_effect=lambda txt: (txt, {"pii_masked": False}),
            ),
        ):
            mock_rag = AsyncMock()
            mock_rag.ingest = AsyncMock(return_value="id-3")
            mock_get.return_value = mock_rag

            await proc.process(exchange, _Context())

        call = mock_rag.ingest.call_args
        assert call.kwargs["content"] == "{'key': 'val'}"

    def test_to_spec_defaults(self) -> None:
        proc = RagIngestProcessor()
        assert proc.to_spec() == {"rag_ingest": {"collection": "default"}}

    def test_to_spec_custom(self) -> None:
        proc = RagIngestProcessor(
            source_property="s", modal="image", collection="c", output_property="o"
        )
        assert proc.to_spec() == {
            "rag_ingest": {
                "source_property": "s",
                "modal": "image",
                "collection": "c",
                "output_property": "o",
            }
        }
