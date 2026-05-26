"""FastMCP HTTP transport (Wave D.4 / Track D AI).

Поднимает MCP-сервер по HTTP/SSE на ``mcp_settings.bind_path``. Mount'ится
в FastAPI через ``app.mount(...)``. Auth-стек реализован отдельным ASGI
middleware (:mod:`auth_middleware`) поверх FastMCP-ASGI app.

FastMCP API различается между версиями (0.x → ``asgi_app()``, 1.x →
``http_app()``/``streamable_http_app()``). Здесь — feature-detect через
``getattr``.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ("create_mcp_http_app",)


def _resolve_http_app(mcp: Any) -> Any:
    """Возвращает ASGI app FastMCP по доступному имени метода.

    Порядок предпочтения:
        1. ``http_app()`` — FastMCP 1.x.
        2. ``streamable_http_app()`` — FastMCP 1.x (streaming).
        3. ``sse_app()`` — FastMCP 0.x.
        4. ``asgi_app()`` — общий FastMCP.
    """
    for attr in ("http_app", "streamable_http_app", "sse_app", "asgi_app"):
        candidate = getattr(mcp, attr, None)
        if candidate is None:
            continue
        try:
            asgi = candidate() if callable(candidate) else candidate
        except Exception as exc:  # noqa: BLE001
            logger.debug("FastMCP.%s() failed: %s", attr, exc)
            continue
        if asgi is not None:
            logger.info("FastMCP HTTP transport resolved via .%s()", attr)
            return asgi
    raise RuntimeError(
        "FastMCP не предоставляет ASGI HTTP API; ожидался один из методов: "
        "http_app / streamable_http_app / sse_app / asgi_app."
    )


def create_mcp_http_app() -> Any:
    """Создаёт ASGI-приложение MCP HTTP transport с auth middleware.

    При ``mcp_gateway_namespaces_enabled=True`` использует MCPGateway
    (ADR-0070, S27 W4) — 3 namespace (credit/analytics/system) aggregator.
    При False — legacy монолитный mcp_server.

    Returns:
        ASGI-приложение (Starlette-совместимое) с прикрученной авторизацией.
        Может быть смонтировано через ``app.mount(prefix, asgi_app)``.

    Raises:
        ImportError: если ``fastmcp`` не установлен.
        RuntimeError: если HTTP transport недоступен в текущей версии.
    """
    from src.backend.entrypoints.mcp.auth_middleware import McpAuthMiddleware

    if _is_namespaces_enabled():
        from src.backend.entrypoints.mcp.gateway import create_mcp_gateway

        mcp = create_mcp_gateway()
        logger.info("MCP HTTP app: using MCPGateway (namespaces enabled)")
    else:
        from src.backend.entrypoints.mcp.mcp_server import create_mcp_server

        mcp = create_mcp_server()
        logger.info("MCP HTTP app: using legacy mcp_server")

    asgi = _resolve_http_app(mcp)
    return McpAuthMiddleware(asgi)


def _is_namespaces_enabled() -> bool:
    """Проверяет feature-flag ``mcp_gateway_namespaces_enabled``.

    Returns:
        True если namespaces enabled и FastMCP version compatible.
    """
    try:
        from src.backend.core.config.features import feature_flags

        return bool(feature_flags.mcp_gateway_namespaces_enabled)
    except Exception:
        return False
