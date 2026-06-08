"""Token-based чанкер (tiktoken с fallback на character-based).

При наличии ``tiktoken`` — точное разбиение по токенам выбранного
encoding'а (по умолчанию ``cl100k_base``, совпадающий с GPT-4/3.5).
Если ``tiktoken`` не установлен — используется character-based fallback
(допустимая аппроксимация для S3 baseline; точный токен-чанкинг
включается автоматически при появлении пакета).
"""

from __future__ import annotations

from typing import Any

from src.backend.infrastructure.logging.factory import get_logger

__all__ = ("TokenChunker",)

logger = get_logger(__name__)


class TokenChunker:
    """Разбиение по токенам с fallback на символы.

    Args:
        chunk_size: Размер чанка в токенах (символах при fallback).
        chunk_overlap: Пересечение в токенах (символах при fallback).
        encoding_name: tiktoken encoding (например, ``cl100k_base``).
    """

    def __init__(
        self, *, chunk_size: int, chunk_overlap: int, encoding_name: str = "cl100k_base"
    ) -> None:
        self._size = chunk_size
        self._overlap = chunk_overlap
        self._encoding_name = encoding_name
        self._encoding = self._load_encoding(encoding_name)

    @staticmethod
    def _load_encoding(name: str) -> Any | None:
        """Возвращает tiktoken encoding или ``None``, если пакет недоступен."""
        try:
            import tiktoken
        except ImportError:
            logger.info(
                "tiktoken не установлен — TokenChunker работает в "
                "character-based fallback режиме"
            )
            return None
        try:
            return tiktoken.get_encoding(name)
        except Exception as exc:
            logger.warning(
                "tiktoken.get_encoding(%r) failed: %s — fallback на character-based",
                name,
                exc,
            )
            return None

    def split(self, text: str) -> list[str]:
        """Разбить ``text`` на список чанков с overlap'ом."""
        if not text:
            return []
        if self._encoding is None:
            return _char_split(text, self._size, self._overlap)
        return self._token_split(text)

    def _token_split(self, text: str) -> list[str]:
        encoding = self._encoding
        assert encoding is not None

        tokens = encoding.encode(text)
        if not tokens:
            return []

        chunks: list[str] = []
        step = self._size - self._overlap
        for start in range(0, len(tokens), step):
            window = tokens[start : start + self._size]
            if not window:
                break
            chunks.append(encoding.decode(window))
            if start + self._size >= len(tokens):
                break
        return [c for c in chunks if c]


def _char_split(text: str, size: int, overlap: int) -> list[str]:
    """Character-based fallback splitter."""
    chunks: list[str] = []
    step = size - overlap
    start = 0
    while start < len(text):
        end = start + size
        piece = text[start:end]
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start += step
    return chunks
