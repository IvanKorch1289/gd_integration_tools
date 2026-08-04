"""Sprint 2.2: PII-masking на single-doc RAG endpoint'ах.

Проверяет, что ``POST /ingest`` (``_RAGFacade.ingest``) и ``POST /upload``
(``_RAGFacade.upload``) маршрутизируются через :class:`RagIngestService` —
а не напрямую в :class:`RAGService` — и потому применяют ``_maybe_mask_pii``
(Block 1.3, ADR-0072).

Тесты подменяют ``get_rag_ingest_service`` на :class:`RagIngestService`,
сконструированный с mock-``RAGService``. ``ingest_text`` выполняется реально —
это доказывает, что PII-mask отрабатывает на single-doc пути endpoint'а.
"""

# ruff: noqa: S101

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import UploadFile

from src.backend.core.config import ai_stack
from src.backend.core.di import providers
from src.backend.entrypoints.api.v1.endpoints import rag as rag_mod
from src.backend.services.ai.rag_ingest_service import RagIngestService


@dataclass(slots=True)
class _StubResult:
    """Stub :class:`SanitizationResult` для DI-injection."""

    sanitized_text: str
    replacements: dict[str, str]


class _DigitSanitizer:
    """Маскирует любые 3+ подряд цифры как ``[REDACTED]``."""

    def sanitize_text(self, text: str) -> _StubResult:
        import re

        cleaned = re.sub(r"\d{3,}", "[REDACTED]", text)
        return _StubResult(
            sanitized_text=cleaned,
            replacements={"[REDACTED]": "***"} if cleaned != text else {},
        )


def _enable_pii_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Включает ``rag_ingest_settings.pii_mask_on_ingest`` + ставит stub sanitizer."""
    monkeypatch.setattr(
        ai_stack.rag_ingest_settings, "pii_mask_on_ingest", True, raising=True
    )
    providers.set_ai_sanitizer_provider(_DigitSanitizer())


def _disable_pii_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Выключает ``rag_ingest_settings.pii_mask_on_ingest``."""
    monkeypatch.setattr(
        ai_stack.rag_ingest_settings, "pii_mask_on_ingest", False, raising=True
    )


def _cleanup_pii_overrides() -> None:
    """Чистит DI-override sanitizer'а после теста."""
    providers.ai._overrides.pop("ai_sanitizer", None)


def _fake_upload_file(content: bytes, filename: str = "doc.txt") -> UploadFile:
    """Минимальный stub UploadFile с переданным содержимым."""
    file = MagicMock(spec=UploadFile)
    file.filename = filename
    file.content_type = "text/plain"
    file.read = AsyncMock(return_value=content)
    return file


def _enable_rag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Включает ``rag_settings.enabled`` (иначе facade бросит 503)."""
    monkeypatch.setattr(
        ai_stack.rag_ingest_settings, "pii_mask_on_ingest", False, raising=True
    )
    from src.backend.core.config import rag as rag_cfg

    monkeypatch.setattr(rag_cfg.rag_settings, "enabled", True, raising=False)


def _build_real_ingest_svc(rag_mock: AsyncMock) -> RagIngestService:
    """Реальный :class:`RagIngestService` с инжектированным mock-RAG."""
    return RagIngestService(rag_service=rag_mock, deferred=False)


class TestIngestRoutesThroughRagIngestService:
    """``_RAGFacade.ingest`` обязан делегировать в ``RagIngestService.ingest_text``."""

    @pytest.mark.asyncio
    async def test_calls_ingest_text_not_rag_directly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Facade вызывает RagIngestService.ingest_text, а не RAGService.ingest напрямую."""
        _enable_rag(monkeypatch)

        rag_service_mock = AsyncMock()
        rag_service_mock.ingest = AsyncMock(return_value="doc-direct")
        ingest_svc = _build_real_ingest_svc(rag_service_mock)

        with patch.object(rag_mod, "get_rag_ingest_service", return_value=ingest_svc):
            resp = await rag_mod._FACADE.ingest(content="hello world", namespace="ns1")

        # RagIngestService.ingest_text вернул doc_id через RAGService.ingest.
        assert resp.doc_id == "doc-direct"
        rag_service_mock.ingest.assert_awaited_once()
        # Namespace и metadata прокинуты.
        call = rag_service_mock.ingest.await_args
        assert call.kwargs["namespace"] == "ns1"

    @pytest.mark.asyncio
    async def test_ingest_masks_pii_when_flag_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """При включённом PII-флаге текст в RAGService уходит замаскированным.

        Regression для Sprint 2.2: раньше ``/ingest`` вызывал
        ``RAGService.ingest()`` напрямую и не маскировал PII.
        """
        _enable_rag(monkeypatch)
        _enable_pii_flag(monkeypatch)
        try:
            rag_service_mock = AsyncMock()
            rag_service_mock.ingest = AsyncMock(return_value="doc-1")
            ingest_svc = _build_real_ingest_svc(rag_service_mock)

            with patch.object(
                rag_mod, "get_rag_ingest_service", return_value=ingest_svc
            ):
                await rag_mod._FACADE.ingest(
                    content="ИНН 7707083893, договор 12345", namespace="ns1"
                )

            call = rag_service_mock.ingest.await_args
            assert call is not None
            text_arg = call.args[0]
            metadata = call.kwargs["metadata"]

            # PII замаскирован (regex \d{3,}).
            assert "7707083893" not in text_arg
            assert "12345" not in text_arg
            assert "[REDACTED]" in text_arg
            assert metadata["pii_masked"] is True
            assert metadata["pii_masker_version"] == "_DigitSanitizer"
        finally:
            _cleanup_pii_overrides()

    @pytest.mark.asyncio
    async def test_ingest_passthrough_when_flag_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """При выключенном PII-флаге текст идёт как есть (legacy behavior сохранён)."""
        _enable_rag(monkeypatch)
        _disable_pii_flag(monkeypatch)

        rag_service_mock = AsyncMock()
        rag_service_mock.ingest = AsyncMock(return_value="doc-1")
        ingest_svc = _build_real_ingest_svc(rag_service_mock)

        with patch.object(rag_mod, "get_rag_ingest_service", return_value=ingest_svc):
            await rag_mod._FACADE.ingest(content="ИНН 7707083893", namespace="ns1")

        call = rag_service_mock.ingest.await_args
        assert call is not None
        text_arg = call.args[0]
        metadata = call.kwargs["metadata"]
        assert text_arg == "ИНН 7707083893"
        assert metadata["pii_masked"] is False

    @pytest.mark.asyncio
    async def test_ingest_propagates_user_metadata(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """User metadata из request доходит до RAG.metadata."""
        _enable_rag(monkeypatch)
        _disable_pii_flag(monkeypatch)

        rag_service_mock = AsyncMock()
        rag_service_mock.ingest = AsyncMock(return_value="doc-1")
        ingest_svc = _build_real_ingest_svc(rag_service_mock)

        with patch.object(rag_mod, "get_rag_ingest_service", return_value=ingest_svc):
            await rag_mod._FACADE.ingest(
                content="x",
                namespace="docs",
                metadata={"tenant_id": "acme", "source": "api"},
            )

        call = rag_service_mock.ingest.await_args
        metadata = call.kwargs["metadata"]
        assert metadata["tenant_id"] == "acme"
        assert metadata["source"] == "api"


class TestUploadRoutesThroughRagIngestService:
    """``_RAGFacade.upload`` обязан делегировать в ``RagIngestService.ingest_text``."""

    @pytest.mark.asyncio
    async def test_calls_ingest_text_not_rag_directly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Facade.upload вызывает RagIngestService.ingest_text для текста из файла."""
        _enable_rag(monkeypatch)

        rag_service_mock = AsyncMock()
        rag_service_mock.ingest = AsyncMock(return_value="doc-up")
        rag_service_mock.chunk_text = MagicMock(return_value=["c1", "c2"])
        ingest_svc = _build_real_ingest_svc(rag_service_mock)

        file = _fake_upload_file(b"plain text body", filename="report.txt")

        with (
            patch.object(rag_mod, "get_rag_service", return_value=rag_service_mock),
            patch.object(rag_mod, "get_rag_ingest_service", return_value=ingest_svc),
        ):
            resp = await rag_mod._FACADE.upload(file=file, namespace="docs")

        assert resp.doc_id == "doc-up"
        rag_service_mock.ingest.assert_awaited_once()
        rag_service_mock.chunk_text.assert_called_once()
        # Filename и source попали в metadata.
        call = rag_service_mock.ingest.await_args
        assert call.kwargs["metadata"]["filename"] == "report.txt"
        assert call.kwargs["metadata"]["source"] == "upload"

    @pytest.mark.asyncio
    async def test_upload_masks_pii_when_flag_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """При включённом PII-флаге текст из multipart-файла маскируется до RAG.

        Regression для Sprint 2.2: раньше ``/upload`` слал текст в RAG
        без маскирования.
        """
        _enable_rag(monkeypatch)
        _enable_pii_flag(monkeypatch)
        try:
            rag_service_mock = AsyncMock()
            rag_service_mock.ingest = AsyncMock(return_value="doc-up-1")
            rag_service_mock.chunk_text = MagicMock(return_value=["c1"])
            ingest_svc = _build_real_ingest_svc(rag_service_mock)

            file = _fake_upload_file(
                b"User phone 79001234567 and card 1234567890123456", filename="leak.txt"
            )

            with (
                patch.object(rag_mod, "get_rag_service", return_value=rag_service_mock),
                patch.object(
                    rag_mod, "get_rag_ingest_service", return_value=ingest_svc
                ),
            ):
                await rag_mod._FACADE.upload(file=file, namespace="docs")

            call = rag_service_mock.ingest.await_args
            assert call is not None
            text_arg = call.args[0]
            metadata = call.kwargs["metadata"]

            # PII замаскирован (regex \d{3,}).
            assert "79001234567" not in text_arg
            assert "1234567890123456" not in text_arg
            assert "[REDACTED]" in text_arg
            # Имя файла и source marker сохранились.
            assert metadata["filename"] == "leak.txt"
            assert metadata["source"] == "upload"
            assert metadata["pii_masked"] is True
        finally:
            _cleanup_pii_overrides()

    @pytest.mark.asyncio
    async def test_upload_preserves_user_metadata(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """User metadata из form-data доходит до RAG.metadata без потерь."""
        _enable_rag(monkeypatch)
        _disable_pii_flag(monkeypatch)

        rag_service_mock = AsyncMock()
        rag_service_mock.ingest = AsyncMock(return_value="doc-up-2")
        rag_service_mock.chunk_text = MagicMock(return_value=["c1"])
        ingest_svc = _build_real_ingest_svc(rag_service_mock)

        file = _fake_upload_file(b"text", filename="doc.txt")

        with (
            patch.object(rag_mod, "get_rag_service", return_value=rag_service_mock),
            patch.object(rag_mod, "get_rag_ingest_service", return_value=ingest_svc),
        ):
            await rag_mod._FACADE.upload(
                file=file,
                namespace="docs",
                metadata_json='{"tenant_id": "acme", "doc_type": "policy"}',
            )

        call = rag_service_mock.ingest.await_args
        metadata = call.kwargs["metadata"]
        assert metadata["tenant_id"] == "acme"
        assert metadata["doc_type"] == "policy"
        assert metadata["source"] == "upload"
        assert metadata["filename"] == "doc.txt"
