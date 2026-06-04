"""MIME-sniff по расширению файла.

Используется в RAG /upload, где ``UploadFile.content_type`` у ряда
клиентов приходит ``application/octet-stream`` без расшифровки.
Расширенный список включает все типы, которые поддерживает markitdown:
PDF/DOCX/PPTX/XLSX/HTML/CSV/JSON + текстовые форматы (MD/TXT).
"""

from __future__ import annotations

__all__ = ("_EXT_TO_MIME", "sniff_mime")


_EXT_TO_MIME: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".html": "text/html",
    ".htm": "text/html",
    ".csv": "text/csv",
    ".json": "application/json",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
}


def sniff_mime(filename: str | None, declared: str | None) -> str:
    """Определяет MIME по расширению, если ``declared`` пуст или ``octet-stream``.

    Args:
        filename: Имя файла (с расширением).
        declared: Заявленный клиентом MIME (например, ``content_type``
            из ``UploadFile``).

    Returns:
        Эффективный MIME-type. Если расширение неизвестно — возвращает
        ``declared`` либо ``application/octet-stream``.
    """
    if declared and declared != "application/octet-stream":
        return declared
    if filename:
        lower = filename.lower()
        for ext, mime in _EXT_TO_MIME.items():
            if lower.endswith(ext):
                return mime
    return declared or "application/octet-stream"
