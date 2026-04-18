"""HMAC-SHA256 подпись и верификация webhooks.

Защита от:
- Подделки запросов (verify signature)
- Replay attacks (timestamp window)
- Timing attacks (hmac.compare_digest)
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

import orjson

__all__ = (
    "sign_payload",
    "verify_signature",
    "InvalidSignatureError",
    "DEFAULT_TIMESTAMP_WINDOW",
)

DEFAULT_TIMESTAMP_WINDOW = 300  # 5 минут


class InvalidSignatureError(Exception):
    """Подпись невалидна или timestamp вне окна."""


def _canonical_body(payload: dict[str, Any] | bytes | str) -> bytes:
    """Канонизирует payload для подписи."""
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode()
    return orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)


def sign_payload(
    payload: dict[str, Any] | bytes | str,
    secret: str,
    timestamp: int | None = None,
) -> tuple[str, int]:
    """Подписывает payload HMAC-SHA256.

    Args:
        payload: Тело запроса (dict/bytes/str).
        secret: Секретный ключ (≥32 байт).
        timestamp: Unix timestamp (если None — текущий).

    Returns:
        (signature, timestamp) — hex-подпись и использованный timestamp.
    """
    ts = timestamp or int(time.time())
    body = _canonical_body(payload)
    message = f"{ts}.".encode() + body
    signature = hmac.new(
        secret.encode(), message, hashlib.sha256
    ).hexdigest()
    return signature, ts


def verify_signature(
    payload: dict[str, Any] | bytes | str,
    signature: str,
    timestamp: int,
    secret: str,
    window_seconds: int = DEFAULT_TIMESTAMP_WINDOW,
) -> bool:
    """Проверяет подпись webhook с защитой от replay.

    Args:
        payload: Полученное тело запроса.
        signature: Значение из X-Webhook-Signature header.
        timestamp: Значение из X-Webhook-Timestamp header.
        secret: Секретный ключ.
        window_seconds: Окно валидности timestamp (по умолчанию 5 минут).

    Returns:
        True если подпись валидна и timestamp в окне.
    """
    now = int(time.time())
    if abs(now - timestamp) > window_seconds:
        return False

    expected, _ = sign_payload(payload, secret, timestamp=timestamp)
    return hmac.compare_digest(expected, signature)


def build_signature_headers(
    payload: dict[str, Any] | bytes | str,
    secret: str,
) -> dict[str, str]:
    """Возвращает headers для исходящего webhook.

    Returns:
        {"X-Webhook-Signature": ..., "X-Webhook-Timestamp": ...}
    """
    signature, ts = sign_payload(payload, secret)
    return {
        "X-Webhook-Signature": signature,
        "X-Webhook-Timestamp": str(ts),
    }
