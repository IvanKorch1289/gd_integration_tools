"""Per-protocol rate-limit helpers (S163 W7, R3 partial).

Расширение :mod:`global_ratelimit` для не-HTTP протоколов
(WebSocket, SSE, MQTT, gRPC).

Назначение:
    * Извлечение tenant-aware identifier из ASGI scope для WebSocket и SSE
      (HTTP-handshake идёт через ``GlobalRateLimitMiddleware``;
      здесь — для post-handshake ``type=websocket`` / SSE stream).
    * Per-topic identifier для MQTT и per-call identifier для gRPC —
      :func:`mqtt_topic_identifier` / :func:`grpc_call_identifier`
      используются внутри своих middleware/interceptor (НЕ через ASGI).

Полная per-message/per-topic rate-limit логика (R3 full scope) — отдельные
sprint-волны: ``WSRateLimitMiddleware``, ``SSERateLimitMiddleware``,
``MQTTRateLimitHandler``, ``GRPCRateLimitInterceptor``. Этот модуль —
ТОЛЬКО identifier-extraction primitives, переиспользуемые в будущем.

ponytail: минимальный scope. Полная интеграция per-protocol rate-limit —
multi-sprint effort. Этот файл — building block.
"""

from __future__ import annotations

from typing import Any


def _decode_header(headers: dict[bytes, bytes] | None, name: bytes) -> str | None:
    """Decode ASGI header value или None если отсутствует."""
    if not headers:
        return None
    value = headers.get(name)
    if value is None:
        return None
    return value.decode("latin-1", errors="replace")


def ws_identifier(scope: dict[str, Any]) -> str:
    """Tenant-aware identifier для WebSocket connection (post-handshake).

    ASGI scope ``type='websocket'`` после HTTP-upgrade.
    Приоритет (matching :func:`global_ratelimit.tenant_aware_identifier`):
        1. ``X-Tenant-ID`` header (multi-tenant).
        2. ``X-User-ID`` header (per-user).
        3. ``client[0]`` IP fallback.

    Args:
        scope: ASGI scope с ``type='websocket'``.

    Returns:
        Идентификатор формата ``ws:<tenant|user|ip>:<host>``.
    """
    headers = dict(scope.get("headers") or ())
    tenant = _decode_header(headers, b"x-tenant-id")
    if tenant:
        return f"ws:tenant:{tenant}"
    user = _decode_header(headers, b"x-user-id")
    if user:
        return f"ws:user:{user}"
    client = scope.get("client") or ("-", 0)
    host = client[0] if isinstance(client, (list, tuple)) else "-"
    return f"ws:ip:{host}"


def sse_identifier(scope: dict[str, Any]) -> str:
    """Tenant-aware identifier для SSE stream.

    SSE использует HTTP-scope (не upgrade), но ``scope['path']`` обычно
    содержит ``/events/...`` или подобный stream-эндпоинт.

    Args:
        scope: ASGI scope с ``type='http'`` (SSE) или stream endpoint.

    Returns:
        Идентификатор формата ``sse:<tenant|user|ip>:<path>``.
    """
    headers = dict(scope.get("headers") or ())
    tenant = _decode_header(headers, b"x-tenant-id")
    if tenant:
        return f"sse:tenant:{tenant}"
    user = _decode_header(headers, b"x-user-id")
    if user:
        return f"sse:user:{user}"
    client = scope.get("client") or ("-", 0)
    host = client[0] if isinstance(client, (list, tuple)) else "-"
    path = scope.get("path", "/")
    return f"sse:ip:{host}:{path}"


def mqtt_topic_identifier(topic: str, client_id: str | None = None) -> str:
    """Per-topic identifier для MQTT rate-limit.

    MQTT broker не имеет ASGI-scope. Эта функция используется в
    ``MQTTRateLimitHandler`` (future R3 sprint).

    Args:
        topic: MQTT topic (e.g., ``tenant/acme/commands``).
        client_id: Optional MQTT client identifier (для per-client override).

    Returns:
        Идентификатор формата ``mqtt:topic:<topic>`` или
        ``mqtt:client:<client_id>:<topic>`` если client_id задан.
    """
    if client_id:
        return f"mqtt:client:{client_id}:{topic}"
    return f"mqtt:topic:{topic}"


def grpc_call_identifier(
    method: str, service: str, *, tenant_id: str | None = None
) -> str:
    """Per-call identifier для gRPC rate-limit interceptor.

    gRPC unary calls и stream calls идентифицируются по (service, method)
    плюс optional tenant context.

    Args:
        method: gRPC method name (e.g., ``GetUser``).
        service: gRPC service name (e.g., ``users.v1.UserService``).
        tenant_id: Optional tenant из metadata.

    Returns:
        Идентификатор формата ``grpc:<tenant|global>:<service>/<method>``.
    """
    if tenant_id:
        return f"grpc:tenant:{tenant_id}:{service}/{method}"
    return f"grpc:global:{service}/{method}"


__all__ = (
    "grpc_call_identifier",
    "mqtt_topic_identifier",
    "sse_identifier",
    "ws_identifier",
)
