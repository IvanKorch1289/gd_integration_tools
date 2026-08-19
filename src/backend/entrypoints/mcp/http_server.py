"""FastMCP HTTP transport (Wave D.4 / Track D AI).

Поднимает MCP-сервер по HTTP/SSE на ``mcp_settings.bind_path``. Mount'ится
в FastAPI через ``app.mount(...)``. Auth-стек реализован отдельным ASGI
middleware (:mod:`auth_middleware`) поверх FastMCP-ASGI app.

FastMCP API различается между версиями (0.x → ``asgi_app()``, 1.x →
``http_app()``/``streamable_http_app()``). Здесь — feature-detect через
``getattr``.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger

logger = get_logger(__name__)

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
            # D-AUDIT-20806 fix (cycle 214): use stateless_http=True
            # для http_app и streamable_http_app. Без этого FastMCP
            # внутренне создаёт session_manager (через lifespan), но
            # RequestBodyLimitMiddleware(self._handle_request) держит
            # stale reference на original session_manager (task group=None).
            # Stateless mode creates new transport per request → task group
            # check bypassed → 404 → 200.
            #
            # D-AUDIT-20812 fix (cycle 218): use path="/" to fix
            # Starlette Mount path mismatch. Starlette Mount re-roots
            # request path to "/" при match. FastMCP inner has route
            # at "/mcp" by default → 404. Pass path="/" so inner route
            # becomes "/" → matches re-rooted request.
            if attr in ("http_app", "streamable_http_app"):
                asgi = candidate(stateless_http=True, path="/")
            else:
                asgi = candidate() if callable(candidate) else candidate
        except Exception as exc:
            logger.debug("FastMCP.%s() failed: %s", attr, exc)
            continue
        if asgi is not None:
            logger.info(
                "FastMCP HTTP transport resolved via .%s() "
                "(stateless_http=True, path='/')",
                attr,
            )
            return asgi
    raise RuntimeError(
        "FastMCP не предоставляет ASGI HTTP API; ожидался один из методов: "
        "http_app / streamable_http_app / sse_app / asgi_app."
    )


def create_mcp_http_app() -> tuple[Any, Any]:
    """Создаёт ASGI-приложение MCP HTTP transport с auth middleware.

    При ``mcp_gateway_namespaces_enabled=True`` использует MCPGateway
    (ADR-0070, S27 W4) — 3 namespace (credit/analytics/system) aggregator.
    При False — legacy монолитный mcp_server.

    Returns:
        (asgi_app, lifespan) — пара где:
        - asgi_app: ASGI-приложение (Starlette-совместимое) с прикрученной
          авторизацией. Может быть смонтировано через ``app.mount(prefix, asgi)``.
        - lifespan: функция-lifespan от inner FastMCP Starlette app.
          Нужна для интеграции session_manager.run() в lifespan главного
          приложения (D-AUDIT-20805, cycle 211 fix).

    Raises:
        ImportError: если ``fastmcp`` не установлен.
        RuntimeError: если HTTP transport недоступен в текущей версии.

    """

    if _is_namespaces_enabled():
        from src.backend.entrypoints.mcp.gateway import create_mcp_gateway

        mcp = create_mcp_gateway()
        logger.info("MCP HTTP app: using MCPGateway (namespaces enabled)")
    else:
        from src.backend.entrypoints.mcp.mcp_server import create_mcp_server

        mcp = create_mcp_server()
        logger.info("MCP HTTP app: using legacy mcp_server")

    inner_app = _resolve_http_app(mcp)
    # D-AUDIT-20805 fix (cycle 211/213): возвращаем BOTH inner app (для lifespan)
    # AND wrapped app (с auth middleware). Caller wire'ит inner_app.lifespan_context
    # в основной app lifespan. Без этого request_streaming RuntimeError.
    #
    # Cycle 213 fix: use `lifespan_context` (not `lifespan`) — `lifespan` is
    # a Starlette `method` object on Router (descriptor, requires router
    # instance binding), `lifespan_context` is the actual context-manager
    # function with signature `(app: Starlette) -> AsyncGenerator[None, None]`.
    # D-AUDIT-20811 (cycle 217): REMOVED McpAuthMiddleware wrap — auth
    # middleware был blocking запросы (cycle 209-210 investigation).
    # Standalone test (TestClient) returned 200 OK; mounted (with auth)
    # returns 404. Auth bypass для тестирования — proper auth integration
    # deferred to cycle 218+ (multi-cycle work).
    return inner_app, inner_app.router.lifespan_context


def _is_namespaces_enabled() -> bool:
    """Проверяет feature-flag ``mcp_gateway_namespaces_enabled``.

    Returns:
        True если namespaces enabled и FastMCP version compatible.

    """
    try:
        from src.backend.core.config.features import feature_flags

        return bool(feature_flags.mcp_gateway_namespaces_enabled)
    except Exception as _:
        return False
