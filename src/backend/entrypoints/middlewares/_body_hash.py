"""Shared body-hash helper (Sprint 171 M5 — централизация).

Раньше 4 middleware имели свою реализацию:
- audit_log.py:71
- admin_audit.py:93
- pii_masking_response.py:158
- response_cache.py:61

Единый источник правды для ``payload_hash`` / ETag.
"""
from __future__ import annotations

import hashlib

__all__ = ("payload_hash", "etag_hash")


def payload_hash(body: bytes | None, *, prefix_len: int | None = 16) -> str:
    """SHA256 hexdigest от body. ``prefix_len`` обрезает до N символов (для компактности).

    Args:
        body: Raw bytes (request body или response body).
        prefix_len: Сколько символов оставить (default 16). ``None`` = полный digest.

    Returns:
        Hex string. ``""`` если body пустой.
    """
    if not body:
        return ""
    digest = hashlib.sha256(body).hexdigest()
    return digest[:prefix_len] if prefix_len else digest


def etag_hash(body: bytes, *, prefix_len: int = 16) -> str:
    """ETag-формат ``"<digest>"`` для response_cache (RFC 7232 weak/strong).

    Args:
        body: Response body.
        prefix_len: Сколько символов hex (default 16).

    Returns:
        ETag string в кавычках. ``""`` если body пустой.
    """
    digest = payload_hash(body, prefix_len=prefix_len)
    return f'"{digest}"' if digest else ""
