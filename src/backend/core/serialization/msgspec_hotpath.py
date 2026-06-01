"""msgspec hotpath serializers (S10 K2 W1, PERF-6.5).

Утилиты для быстрой JSON-сериализации на hot-path:

* Exchange envelope (idempotency hash, audit emit, WS broadcast);
* Audit events (compact JSON для DLQ/log sinks);
* Cache key builder (детерминированный stable hash);
* WebSocket frame encode.

API::

    from src.backend.core.serialization.msgspec_hotpath import (
        encode_json, decode_json, hash_cache_key, encode_ws_frame,
    )

    payload = encode_json({"event": "x", "id": 42})  # bytes
    key = hash_cache_key("tenant=1", "route_id=credit_v2")
    frame = encode_ws_frame({"type": "ping"})

Fallback: если msgspec не установлен — деградирует на orjson
(остаётся в hot-path ради совместимости). Перформанс деградирует,
но не падает.
"""

from __future__ import annotations

import hashlib
from typing import Any

__all__ = (
    "MSGSPEC_AVAILABLE",
    "decode_json",
    "encode_audit_event",
    "encode_json",
    "encode_ws_frame",
    "hash_cache_key",
)

try:
    import msgspec

    _ENCODER = msgspec.json.Encoder()
    _DECODER = msgspec.json.Decoder()
    MSGSPEC_AVAILABLE = True
except ImportError:  # pragma: no cover — fallback path
    msgspec = None
    _ENCODER = None
    _DECODER = None
    MSGSPEC_AVAILABLE = False

if not MSGSPEC_AVAILABLE:
    import orjson


def encode_json(value: Any) -> bytes:
    """JSON-encode → bytes (msgspec → orjson fallback).

    Не возвращает str — bytes для прямой передачи в HTTP/WS/Kafka.
    """
    if MSGSPEC_AVAILABLE:
        return _ENCODER.encode(value)
    return orjson.dumps(value)


def decode_json(data: bytes | str) -> Any:
    """JSON-decode → Python objects (msgspec → orjson fallback)."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    if MSGSPEC_AVAILABLE:
        return _DECODER.decode(data)
    return orjson.loads(data)


def hash_cache_key(*parts: str) -> str:
    """Stable SHA-256 hash из argv-частей. 16-char prefix для cache key.

    Используется в hot-path кэшировании (response cache, rate-limit
    bucket key). Гарантирует:

    * детерминизм между процессами (нет per-process random);
    * lock-free (только stdlib).
    """
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


def encode_ws_frame(value: dict[str, Any]) -> bytes:
    """JSON-frame для WebSocket broadcast — alias encode_json."""
    return encode_json(value)


def encode_audit_event(
    *,
    action: str,
    actor: str,
    resource: str | None = None,
    tenant_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> bytes:
    """Сериализует typed-audit event с минимальной аллокацией.

    Подходит для DLQ writer и Kafka audit sink — не парсит
    Pydantic-модель, а сразу формирует JSON payload.
    """
    payload: dict[str, Any] = {"action": action, "actor": actor}
    if resource is not None:
        payload["resource"] = resource
    if tenant_id is not None:
        payload["tenant_id"] = tenant_id
    if extra:
        payload["extra"] = extra
    return encode_json(payload)
