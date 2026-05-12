"""Тесты IngestFileProcessor (Sprint S5)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus
from src.backend.dsl.engine.processors.ingest_file import IngestFileProcessor


def _exchange(properties: dict | None = None) -> Exchange:
    ex = Exchange()
    if properties:
        ex.properties.update(properties)
    return ex


def _context() -> ExecutionContext:
    return ExecutionContext()


class TestValidation:
    def test_requires_source(self) -> None:
        with pytest.raises(ValueError, match="s3_key_from или data_property"):
            IngestFileProcessor()

    def test_invalid_on_unsupported(self) -> None:
        with pytest.raises(ValueError, match="on_unsupported"):
            IngestFileProcessor(data_property="x", on_unsupported="skip")

    def test_invalid_engine(self) -> None:
        with pytest.raises(ValueError, match="engine"):
            IngestFileProcessor(data_property="x", engine="docling")


class TestDataPropertySource:
    async def test_bytes_property_parsed_legacy_text(self) -> None:
        ex = _exchange({"raw_doc": b"hello"})
        proc = IngestFileProcessor(
            data_property="raw_doc",
            mime_from="properties.declared_mime",
            result_property="doc",
        )
        ex.set_property("declared_mime", "text/plain")
        await proc.process(ex, _context())
        result = ex.get_property("doc")
        assert result is not None
        assert result["text"] == "hello"
        assert result["engine"] == "legacy"
        assert result["markdown"] is False

    async def test_str_property_encoded(self) -> None:
        ex = _exchange({"raw": "world", "mime": "text/plain"})
        proc = IngestFileProcessor(
            data_property="raw", mime_from="properties.mime", result_property="doc"
        )
        await proc.process(ex, _context())
        result = ex.get_property("doc")
        assert result["text"] == "world"


class TestOnUnsupportedFail:
    async def test_fails_exchange_on_unknown_mime(self) -> None:
        ex = _exchange({"raw": b"<?xml?>", "mime": "application/x-unknown"})
        proc = IngestFileProcessor(
            data_property="raw",
            mime_from="properties.mime",
            on_unsupported="fail",
            result_property="doc",
        )
        await proc.process(ex, _context())
        assert ex.status == ExchangeStatus.failed
        assert "не поддерживается" in (ex.error or "")


class TestOnUnsupportedWarn:
    async def test_warn_writes_skipped_engine_meta(self) -> None:
        ex = _exchange({"raw": b"<?xml?>", "mime": "application/x-unknown"})
        proc = IngestFileProcessor(
            data_property="raw",
            mime_from="properties.mime",
            on_unsupported="warn",
            result_property="doc",
        )
        await proc.process(ex, _context())
        assert ex.status != ExchangeStatus.failed
        result = ex.get_property("doc")
        assert result["text"] is None
        assert result["engine"] == "skipped"
        assert len(result["warnings"]) >= 1


class TestEngineForce:
    async def test_engine_markitdown_fails_when_unavailable(self) -> None:
        ex = _exchange({"raw": b"%PDF-1.0", "mime": "application/pdf"})
        proc = IngestFileProcessor(
            data_property="raw",
            mime_from="properties.mime",
            engine="markitdown",
            on_unsupported="fail",
            result_property="doc",
        )
        # Markitdown упал → orchestrator fallback на legacy → meta.engine='legacy'.
        # IngestFileProcessor видит engine != 'markitdown' → ValueError →
        # on_unsupported='fail' → exchange.fail.
        with (
            patch(
                "src.backend.services.ai.document_parsers._orchestrator._try_markitdown"
            ) as mock_md,
            patch(
                "src.backend.services.ai.document_parsers._orchestrator._parse_pdf"
            ) as mock_pdf,
        ):
            mock_md.side_effect = RuntimeError("missing")
            mock_pdf.return_value = ("plain text", [])
            await proc.process(ex, _context())
        assert ex.status == ExchangeStatus.failed
        assert "markitdown" in (ex.error or "").lower()

    async def test_engine_auto_used_by_default(self) -> None:
        ex = _exchange({"raw": b"hello", "mime": "text/plain"})
        proc = IngestFileProcessor(
            data_property="raw", mime_from="properties.mime", result_property="doc"
        )
        # engine=auto — markitdown пропускается для plain-text.
        await proc.process(ex, _context())
        result = ex.get_property("doc")
        assert result["engine"] == "legacy"


class TestSpecRoundTrip:
    def test_to_spec_includes_all_params(self) -> None:
        proc = IngestFileProcessor(
            s3_key_from="properties.key",
            mime_from="properties.mime",
            result_property="doc",
            on_unsupported="warn",
            engine="auto",
        )
        spec = proc.to_spec()
        assert "ingest_file" in spec
        body = spec["ingest_file"]
        assert body["s3_key_from"] == "properties.key"
        assert body["mime_from"] == "properties.mime"
        assert body["result_property"] == "doc"
        assert body["on_unsupported"] == "warn"
        assert body["engine"] == "auto"
