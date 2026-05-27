"""Общие утилиты для всех страниц."""

from __future__ import annotations

import re
from typing import Any


def sanitize_label(text: str) -> str:
    """Удалить HTML-tags из текста для безопасного отображения в Streamlit."""
    return re.sub(r"<[^>]+>", "", text)


def format_bytes(size: int) -> str:
    """Форматировать байты в человекочитаемый вид."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def format_duration(ms: int) -> str:
    """Форматировать миллисекунды в читаемую строку."""
    if ms < 1000:
        return f"{ms}ms"
    seconds = ms / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.1f}m"
    hours = minutes / 60
    return f"{hours:.1f}h"


def chunked(iterable: list[Any], size: int) -> list[list[Any]]:
    """Разбить список на чанки заданного размера."""
    return [iterable[i : i + size] for i in range(0, len(iterable), size)]


__all__ = ["sanitize_label", "format_bytes", "format_duration", "chunked"]
