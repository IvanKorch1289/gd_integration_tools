"""Regression-тест cycle-4/D-AUDIT-140: IngestMixin.chunk_text использует RecursiveChunker.

Проверяет что naive sliding-window chunker заменён на рекурсивный chunker
через фабрику ``get_chunker("recursive", ...)``.
"""

from __future__ import annotations

from src.backend.services.ai.rag_service.ingest_mixin import IngestMixin


def _mixin() -> IngestMixin:
    """Создаёт IngestMixin без реального RAGService-окружения."""
    obj = IngestMixin.__new__(IngestMixin)
    obj._store = None  # type: ignore[attr-defined]
    obj._embedder = None  # type: ignore[attr-defined]
    obj._cache = None  # type: ignore[attr-defined]
    return obj


def test_chunk_text_short_text_single_chunk() -> None:
    """cycle-4/D-AUDIT-140: короткий текст → один чанк."""
    assert _mixin().chunk_text("короткий") == ["короткий"]


def test_chunk_text_paragraphs_preserved() -> None:
    """cycle-4/D-AUDIT-140: RecursiveChunker не разрезает абзацы посередине."""
    text = (
        "Первый параграф. Содержит несколько предложений.\n\n"
        "Второй параграф. Тоже содержит текст.\n\n"
        "Третий параграф. Короткий."
    )
    chunks = _mixin().chunk_text(text)
    assert len(chunks) >= 1
    joined = "".join(chunks)
    # Оба абзаца сохранены, ничего не разрезано.
    assert "Первый параграф" in joined
    assert "Третий параграф" in joined


def test_chunk_text_long_text_produces_multiple_chunks() -> None:
    """cycle-4/D-AUDIT-140: длинный текст → несколько чанков через рекурсию."""
    text = ("Предложение номер один. " * 50 + "\n\n") * 5
    chunks = _mixin().chunk_text(text)
    assert len(chunks) > 1
    assert all(c for c in chunks)
