"""Unit-тесты ``services.ai.rag.multimodal`` — coverage ratchet (Post-Plan A Sprint 30).

core/ai/rag/multimodal subpackage (K4 W1 multimodal RAG): re-exports
10 symbols (MultimodalRAGService + 2 Ingesters PDF/Image + 2 Embedders
CLIP/Colpali + ChunkDoc + IngestResult + SearchResult + MultimodalEntry
+ get_multimodal_rag singleton). ~15 stmts, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class identity + singleton callable.
"""

from __future__ import annotations

import pytest

from src.backend.services.ai.rag import multimodal
from src.backend.services.ai.rag.multimodal import (
    ChunkDoc,
    CLIPEmbedder,
    ColpaliEmbedder,
    ImageIngester,
    IngestResult,
    LazyImportError,
    MultimodalEntry,
    MultimodalRAGService,
    PDFIngester,
    SearchResult,
    get_multimodal_rag,
)


@pytest.mark.unit
class TestMultimodalFacadeAllExports:
    """``__all__`` audit + class/callable identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        [
            "ChunkDoc",
            "CLIPEmbedder",
            "ColpaliEmbedder",
            "ImageIngester",
            "IngestResult",
            "LazyImportError",
            "MultimodalEntry",
            "MultimodalRAGService",
            "PDFIngester",
            "SearchResult",
            "get_multimodal_rag",
        ],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(multimodal, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in multimodal.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 11 символов."""
        assert len(multimodal.__all__) == 11

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает MultimodalRAG (K4 W1)."""
        assert multimodal.__doc__ is not None
        assert "Multimodal" in multimodal.__doc__ or "multimodal" in multimodal.__doc__.lower()


@pytest.mark.unit
class TestMultimodalFacadeIdentity:
    """Identity checks для 10 re-exports."""

    def test_multimodal_rag_service_is_class(self) -> None:
        """``MultimodalRAGService`` — class (main facade)."""
        assert isinstance(MultimodalRAGService, type)

    def test_pdf_ingester_is_class(self) -> None:
        """``PDFIngester`` — class (PDF→chunks via pypdfium2)."""
        assert isinstance(PDFIngester, type)

    def test_image_ingester_is_class(self) -> None:
        """``ImageIngester`` — class (Image→ChunkDoc via Pillow)."""
        assert isinstance(ImageIngester, type)

    def test_clip_embedder_is_class(self) -> None:
        """``CLIPEmbedder`` — class (CLIP embedder)."""
        assert isinstance(CLIPEmbedder, type)

    def test_colpali_embedder_is_class(self) -> None:
        """``ColpaliEmbedder`` — class (Colpali embedder, lazy)."""
        assert isinstance(ColpaliEmbedder, type)

    def test_chunk_doc_is_class(self) -> None:
        """``ChunkDoc`` — class (data model)."""
        assert isinstance(ChunkDoc, type)

    def test_ingest_result_is_class(self) -> None:
        """``IngestResult`` — class (result dataclass)."""
        assert isinstance(IngestResult, type)

    def test_search_result_is_class(self) -> None:
        """``SearchResult`` — class (result dataclass)."""
        assert isinstance(SearchResult, type)

    def test_multimodal_entry_is_class(self) -> None:
        """``MultimodalEntry`` — class (back-compat scaffold)."""
        assert isinstance(MultimodalEntry, type)

    def test_get_multimodal_rag_is_callable(self) -> None:
        """``get_multimodal_rag`` — callable (singleton getter)."""
        assert callable(get_multimodal_rag)

    def test_lazy_import_error_is_exception(self) -> None:
        """``LazyImportError`` — Exception subclass (lazy import failure)."""
        assert isinstance(LazyImportError, type)
        assert issubclass(LazyImportError, Exception)
