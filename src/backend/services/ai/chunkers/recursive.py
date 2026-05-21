"""Рекурсивный чанкер — разбиение по иерархии separator'ов с overlap.

Логика близка к LangChain ``RecursiveCharacterTextSplitter``: жадно
расщепляем по самому крупному separator'у, при необходимости
рекурсивно дробим оставшиеся слишком длинные фрагменты следующим
separator'ом и так до посимвольного резерва.
"""

from __future__ import annotations

__all__ = ("RecursiveChunker",)


_DEFAULT_SEPARATORS: tuple[str, ...] = ("\n\n", "\n", ". ", " ", "")


class RecursiveChunker:
    """Рекурсивное character-based разбиение по separator'ам.

    Args:
        chunk_size: Целевой размер чанка в символах.
        chunk_overlap: Пересечение между соседями в символах.
        separators: Иерархия separator'ов от самого крупного к мелкому.
            Пустая строка означает посимвольное разбиение.
    """

    def __init__(
        self,
        *,
        chunk_size: int,
        chunk_overlap: int,
        separators: tuple[str, ...] = _DEFAULT_SEPARATORS,
    ) -> None:
        self._size = chunk_size
        self._overlap = chunk_overlap
        self._separators = separators

    def split(self, text: str) -> list[str]:
        """Разбить ``text`` рекурсивно по separator'ам."""
        if not text:
            return []
        return self._merge(self._split_recursive(text, self._separators))

    def _split_recursive(self, text: str, separators: tuple[str, ...]) -> list[str]:
        if not text:
            return []
        if len(text) <= self._size:
            return [text]

        if not separators:
            return [text[i : i + self._size] for i in range(0, len(text), self._size)]

        sep, *rest = separators
        rest_t = tuple(rest)
        parts = list(text) if sep == "" else text.split(sep)

        result: list[str] = []
        for part in parts:
            if not part:
                continue
            piece = part if sep == "" else part
            if len(piece) <= self._size:
                result.append(piece)
            else:
                result.extend(self._split_recursive(piece, rest_t))
        return result

    def _merge(self, parts: list[str]) -> list[str]:
        """Склеить мелкие фрагменты в чанки до ``chunk_size`` с overlap'ом."""
        if not parts:
            return []

        chunks: list[str] = []
        buf: list[str] = []
        buf_len = 0

        for part in parts:
            part_len = len(part)
            if buf and buf_len + part_len > self._size:
                chunks.append("".join(buf))
                buf, buf_len = self._tail(buf, self._overlap)
            buf.append(part)
            buf_len += part_len

        if buf:
            chunks.append("".join(buf))
        return [c for c in chunks if c]

    @staticmethod
    def _tail(buf: list[str], overlap: int) -> tuple[list[str], int]:
        """Берёт хвост ``buf`` суммарной длины не более ``overlap`` символов."""
        if overlap <= 0:
            return [], 0
        tail: list[str] = []
        total = 0
        for piece in reversed(buf):
            piece_len = len(piece)
            if total + piece_len > overlap and tail:
                break
            tail.insert(0, piece)
            total += piece_len
            if total >= overlap:
                break
        return tail, total
