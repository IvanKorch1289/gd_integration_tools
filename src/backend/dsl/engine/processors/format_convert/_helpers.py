"""Shared helpers для format_convert package (S53 W1 extraction)."""

from __future__ import annotations

from typing import Any


def _to_text(data: Any) -> str:
    """bytes/bytearray → str (utf-8 best-effort)."""
    if isinstance(data, (bytes, bytearray)):
        return data.decode("utf-8", errors="replace")
    return data



