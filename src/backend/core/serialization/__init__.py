"""Сериализаторы hot-path (S10 K2 W1, PERF-6.5)."""

from __future__ import annotations

from src.backend.core.serialization.msgspec_hotpath import (
    MSGSPEC_AVAILABLE,
    decode_json,
    encode_audit_event,
    encode_json,
    encode_ws_frame,
    hash_cache_key,
)

__all__ = (
    "MSGSPEC_AVAILABLE",
    "decode_json",
    "encode_audit_event",
    "encode_json",
    "encode_ws_frame",
    "hash_cache_key",
)
