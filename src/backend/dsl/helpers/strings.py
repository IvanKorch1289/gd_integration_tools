"""String helpers: slugify, mask, pii redact."""

from __future__ import annotations

import re
import unicodedata

__all__ = ("mask", "redact_pii", "slugify")


def slugify(value: str) -> str:
    """Преобразует строку в URL-slug (ASCII, lowercase, дефисы вместо пробелов)."""
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    return re.sub(r"[-\s]+", "-", value)


def mask(
    value: str, *, keep_first: int = 2, keep_last: int = 2, char: str = "*"
) -> str:
    """Маскирует середину строки, оставляя ``keep_first``/``keep_last`` символов."""
    if len(value) <= keep_first + keep_last:
        return char * len(value)
    return (
        value[:keep_first]
        + char * (len(value) - keep_first - keep_last)
        + value[-keep_last:]
    )


def redact_pii(text: str) -> str:
    """Минимальный PII redactor: email + телефон + ИНН."""
    text = re.sub(r"[\w\.-]+@[\w\.-]+", "<email>", text)
    text = re.sub(r"\+?\d[\d\s()-]{7,}", "<phone>", text)
    return re.sub(r"\b\d{10,12}\b", "<inn>", text)
