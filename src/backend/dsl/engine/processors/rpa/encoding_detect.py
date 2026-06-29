"""EncodingDetectProcessor (M25 P3 #8, D277).

Encoding detection по BOM + UTF-8 validation (Ponytail YAGNI: stdlib only).
Pattern (D277): thin wrapper.
"""
# ruff: noqa: E501
from __future__ import annotations

from src.backend.core.logging import get_logger

_logger = get_logger("dsl.rpa.encoding_detect")

__all__ = ("EncodingDetectProcessor",)


class EncodingDetectProcessor:
    """Encoding detection по BOM + UTF-8 validation (stdlib only, D277)."""

    def detect(self, data: bytes) -> str:
        """Detect encoding по BOM + UTF-8 validation.

        Args:
            data: file content (первые 4 байта для BOM, до 16 для UTF-8).

        Returns:
            Encoding string (default: utf-8 для валидного).
        """
        if not data:
            return "utf-8"
        # Check BOMs
        if data[:3] == b"\xef\xbb\xbf":
            return "utf-8-sig"
        if data[:2] == b"\xff\xfe":
            return "utf-16-le"
        if data[:2] == b"\xfe\xff":
            return "utf-16-be"
        # Try UTF-8
        try:
            data.decode("utf-8")
            return "utf-8"
        except UnicodeDecodeError:
            pass
        # Latin-1 fallback (D277: stdlib only)
        return "latin-1"
