"""FastAPI OpenTelemetry middleware для auto-tracing HTTP-запросов (cycle 56 pure ASGI).

Создаёт span `http.{METHOD} {path}` на каждый входящий HTTP-запрос,
насыщает его стандартными HTTP- и app-атрибутами и распространяет
контекст через `traceparent` header (W3C Trace Context).

Ключевые атрибуты span:
    * http.method / http.url / http.route / http.status_code
    * http.user_agent / http.client_ip
    * app.tenant_id (из `X-Tenant-ID` или `current_tenant()`)
    * correlation.id / request.id (из `state['correlation_id']`)
    * app.route_id — если известен из DSL match

Интеграция с распределённой трассировкой:
    * Входящий `traceparent` → continue span (через `TraceContextTextMapPropagator`).
    * Outbound — inject актуальный `traceparent` в response headers,
      чтобы downstream hops (webhook consumers, SSE clients) видели
      единый trace.

Cycle 56: переписано с ``BaseHTTPMiddleware`` на pure ASGI для
архитектурной консистентности с cycle 33-55 (L1 middlewares).

Cycle 56 design: OTEL tracing wrap через ``start_as_current_span``
context manager. Span создаётся при start, response при finish. В
pure ASGI — НЕ try/finally с response.return (нельзя в pure ASGI),
а через send-wrapper, который injects traceparent в
http.response.start headers.
"""

from __future__ import annotations

from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.backend.core.logging import get_logger

__all__ = ("OtelMiddleware",)

logger = get_logger("infra.otel.middleware")


class OtelMiddleware:
    """Pure ASGI middleware: auto-tracing HTTP-запросов через OpenTelemetry (cycle 56).

    Args:
        app: ASGI-приложение.

    """

    def __init__(self, app: ASGIApp) -> None:
        """Инициализирует middleware и пытается загрузить OTEL-зависимости.

        Args:
            app: ASGI-приложение.

        """
        self.app = app
        self._tracer = self._load_tracer()
        self._propagator = self._load_propagator()

    @staticmethod
    def _load_tracer() -> Any:
        """Пытается получить OTEL tracer; возвращает None при отсутствии SDK."""
        try:
            from opentelemetry import trace

            return trace.get_tracer("gd.entrypoints.http")
        except ImportError:
            logger.debug("OpenTelemetry SDK not available — OtelMiddleware is no-op")
            return None
        except (AttributeError, RuntimeError, ValueError, TypeError) as exc:  # pragma: no cover — defensive
            # cycle-9/D-AUDIT-1019: narrow exceptions + observability.
            # AttributeError — tracer_provider API change, RuntimeError —
            # tracer unavailable, ValueError — invalid config, TypeError —
            # wrong arg type.
            logger.warning("Failed to init OTEL tracer: %s", exc)
            return None

    @staticmethod
    def _load_propagator() -> Any:
        """Загружает W3C trace-context propagator или возвращает None."""
        try:
            from opentelemetry.trace.propagation.tracecontext import (
                TraceContextTextMapPropagator,
            )

            return TraceContextTextMapPropagator()
        except ImportError:
            return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Оборачивает обработку запроса в OTEL span.

        Args:
            scope: ASGI scope.
            receive: ASGI receive callable.
            send: ASGI send callable.

        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if self._tracer is None:
            # No tracer → no-op pass-through.
            await self.app(scope, receive, send)
            return

        ctx = self._extract_context(scope)
        method = scope.get("method", "GET").lower()
        path = scope.get("path", "")
        span_name = f"http.{method} {path}"
        attributes = self._build_attributes(scope)

        try:
            from opentelemetry.trace import SpanKind
        except ImportError:
            await self.app(scope, receive, send)
            return

        span_cm = self._tracer.start_as_current_span(
            span_name, context=ctx, kind=SpanKind.SERVER, attributes=attributes,
        )

        # D-AUDIT-A2-03 fix (cycle 1): scope["state"] для per-request state
        # вместо instance attribute. Ранее self._cycle56_status сохранялся
        # на middleware instance — shared между всеми concurrent requests
        # → race condition (status code от request A мог попасть в response B).
        scope.setdefault("state", {})["otel_response_status"] = 0
        response_body_chunks: list[bytes] = []

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                scope["state"]["otel_response_status"] = message.get("status", 200)
                # Get original headers + inject traceparent.
                new_headers = list(message.get("headers", []))
                self._inject_traceparent_to_headers(new_headers)
                # Suppress original — отправим свой с traceparent.
                await send(
                    {
                        "type": "http.response.start",
                        "status": scope["state"]["otel_response_status"],
                        "headers": new_headers,
                    },
                )
            elif message["type"] == "http.response.body":
                # Body пропускаем unchanged (не suppress, т.к. body не
                # модифицируется — только headers injection).
                response_body_chunks.append(message.get("body", b""))
                await send(message)
            else:
                await send(message)

        try:
            with span_cm as span:
                await self._process(scope, receive, send_wrapper, span)
        except Exception:
            # Ошибка уже размечена в _process — пробрасываем.
            raise

    async def _process(
        self, scope: Scope, receive: Receive, send: Send, span: Any,
    ) -> None:
        """Выполняет call_next, помечая span при ошибке (cycle 56 helper)."""
        try:
            await self.app(scope, receive, send)
        except Exception as exc:
            self._mark_error(span, exc)
            raise
        else:
            # Get status from send_wrapper (D-AUDIT-A2-03 fix cycle 1:
            # stored on scope['state'] — per-request, не instance attribute).
            try:
                response_status = scope.get("state", {}).get(
                    "otel_response_status", 200,
                )
                span.set_attribute("http.status_code", response_status)
                if response_status >= 500:
                    self._mark_error(span, RuntimeError(f"HTTP {response_status}"))
            except (AttributeError, TypeError):  # noqa: violation-check — OTel API surface best-effort
                pass

            # Post-response context: route_id может быть выставлен downstream.
            state = scope.get("state", {}) if "state" in scope else {}
            route_id = state.get("route_id") if isinstance(state, dict) else None
            if route_id:
                try:
                    span.set_attribute("app.route_id", str(route_id))
                except (AttributeError, TypeError):
                    pass

    def _extract_context(self, scope: Scope) -> Any:
        """Извлекает W3C trace-context из входящих заголовков (cycle 56 helper)."""
        if self._propagator is None:
            return None
        try:
            # Build carrier from ASGI scope headers (lowercase keys).
            carrier = {
                h[0].decode("latin-1"): h[1].decode("latin-1")
                for h in scope.get("headers", [])
            }
            return self._propagator.extract(carrier=carrier)
        except (AttributeError, KeyError, UnicodeDecodeError, RuntimeError, TypeError):  # pragma: no cover
            # cycle-9/D-AUDIT-1021: narrow exceptions + observability.
            # AttributeError — scope.get API change, KeyError — missing
            # header, UnicodeDecodeError — bad header encoding,
            # RuntimeError — propagator unavailable, TypeError — wrong arg.
            return None

    def _inject_traceparent_to_headers(
        self, headers: list[tuple[bytes, bytes]],
    ) -> None:
        """Cycle 56: injects traceparent в список headers (in-place)."""
        if self._propagator is None:
            return
        carrier: dict[str, str] = {}
        try:
            self._propagator.inject(carrier)
        except (AttributeError, RuntimeError, TypeError, ValueError):  # pragma: no cover
            # cycle-9/D-AUDIT-1021: см. выше — narrow для inject path.
            return
        for key, value in carrier.items():
            headers.append((key.encode("latin-1"), value.encode("latin-1")))

    @staticmethod
    def _build_attributes(scope: Scope) -> dict[str, Any]:
        """Формирует стартовый набор OTEL-атрибутов HTTP-span-а (cycle 56)."""
        # Извлекаем headers из scope.
        headers_dict: dict[str, str] = {}
        for header_name, header_value in scope.get("headers", []):
            try:
                headers_dict[header_name.decode("latin-1").lower()] = (
                    header_value.decode("latin-1")
                )
            except UnicodeDecodeError:
                continue

        method = scope.get("method", "")
        path = scope.get("path", "")
        full_url = scope.get("scheme", "http") + "://" + str(
            scope.get("server", ("", "")),
        ) + path
        # Reconstruct full URL from scheme + server + path + query.
        scheme = scope.get("scheme", "http")
        server = scope.get("server", ("", ""))
        query = scope.get("query_string", b"")
        host_header = headers_dict.get("host", "")
        if host_header:
            full_url = f"{scheme}://{host_header}{path}"
        else:
            full_url = f"{scheme}://{server[0]}{path}"
        if query:
            full_url += f"?{query.decode('latin-1', errors='replace')}"

        client = scope.get("client")
        client_ip = client[0] if client else ""
        user_agent = headers_dict.get("user-agent", "")[:200]

        # Tenant: сначала header, потом ContextVar.
        tenant_id = headers_dict.get("x-tenant-id", "")
        if not tenant_id:
            try:
                from src.backend.core.tenancy import current_tenant

                ctx = current_tenant()
                if ctx is not None:
                    tenant_id = getattr(ctx, "tenant_id", "") or ""
            except (ImportError, AttributeError, RuntimeError) as ten_exc:
                # cycle-9/D-AUDIT-1003: narrow exceptions + observability.
                # ImportError — tenancy missing, AttributeError — API
                # change, RuntimeError — context unavailable.
                import logging
                logging.getLogger(__name__).debug(
                    "otel_middleware.current_tenant_fallback",
                    extra={"error": str(ten_exc)},
                )
                tenant_id = ""

        # Correlation/request id из state (cycle 52 pattern).
        state = scope.get("state", {}) if "state" in scope else {}
        correlation_id = (
            state.get("correlation_id", "")
            if isinstance(state, dict)
            else ""
        )
        request_id = (
            state.get("request_id", "")
            if isinstance(state, dict)
            else ""
        )

        attrs: dict[str, Any] = {
            "http.method": method,
            "http.url": full_url,
            "http.route": path,
            "http.client_ip": client_ip,
            "http.user_agent": user_agent,
            "app.tenant_id": tenant_id,
            "correlation.id": correlation_id,
            "request.id": request_id,
        }
        return attrs

    @staticmethod
    def _mark_error(span: Any, exc: BaseException) -> None:
        """Cycle 56: помечает span как error + records exception."""
        try:
            from opentelemetry.trace import Status, StatusCode

            span.set_status(Status(StatusCode.ERROR, str(exc)))
        except ImportError:  # noqa: violation-check — opentelemetry optional
            pass
        except (AttributeError, RuntimeError, ValueError, TypeError):  # pragma: no cover  # noqa: violation-check — OTel API surface best-effort
            # cycle-9/D-AUDIT-1020: narrow exceptions + observability.
            # AttributeError — Status/StatusCode API change, RuntimeError
            # — set_status unavailable, ValueError/TypeError — invalid args.
            pass
        try:
            span.record_exception(exc)
        except (AttributeError, RuntimeError, ValueError, TypeError):  # pragma: no cover  # noqa: violation-check — OTel API surface best-effort
            # cycle-9/D-AUDIT-1020: см. выше — тот же narrow для record_exception.
            pass
