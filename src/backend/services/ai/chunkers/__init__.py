"""RAG chunkers — стратегии разбиения текста на embedding-чанки.

Доступные стратегии:

* ``token`` — токен-ориентированное (через ``tiktoken``, fallback на
  character-based) разбиение фиксированными окнами с overlap;
* ``recursive`` — рекурсивное расщепление по separators
  (``\\n\\n`` → ``\\n`` → ``. `` → ``" "`` → char), с overlap.

Все чанкеры реализуют :class:`Chunker` (Protocol). Фабрика
:func:`get_chunker` возвращает реализацию по имени стратегии.
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

__all__ = ("Chunker", "ChunkStrategy", "get_chunker")

ChunkStrategy = Literal["token", "recursive"]


@runtime_checkable
class Chunker(Protocol):
    """Стратегия разбиения текста на чанки фиксированного размера/токенов."""

    def split(self, text: str) -> list[str]:
        """Разбить ``text`` на список чанков (без пустых строк)."""
        ...


def get_chunker(
    strategy: ChunkStrategy,
    *,
    chunk_size: int,
    chunk_overlap: int,
    encoding_name: str = "cl100k_base",
) -> Chunker:
    """Фабрика чанкеров по имени стратегии.

    Args:
        strategy: ``"token"`` или ``"recursive"``.
        chunk_size: Целевой размер чанка (в токенах для ``token``,
            в символах для ``recursive``).
        chunk_overlap: Размер пересечения между соседними чанками.
        encoding_name: Имя tiktoken-encoding (используется только в
            стратегии ``"token"``; игнорируется для ``"recursive"``).

    Returns:
        Конкретная реализация :class:`Chunker`.

    Raises:
        ValueError: Неизвестная стратегия или невалидные параметры.
    """
    if chunk_size <= 0:
        raise ValueError(f"chunk_size must be > 0, got {chunk_size}")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError(
            f"chunk_overlap must be in [0, chunk_size), got {chunk_overlap}"
        )

    match strategy:
        case "token":
            from src.backend.services.ai.chunkers.token import TokenChunker

            return TokenChunker(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                encoding_name=encoding_name,
            )
        case "recursive":
            from src.backend.services.ai.chunkers.recursive import RecursiveChunker

            return RecursiveChunker(
                chunk_size=chunk_size, chunk_overlap=chunk_overlap
            )
        case _:
            raise ValueError(
                f"Unknown chunk strategy: {strategy!r}. "
                f"Valid: 'token', 'recursive'"
            )
