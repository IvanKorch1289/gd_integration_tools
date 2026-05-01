"""FastAPI OpenTelemetry middleware для auto-tracing HTTP-запросов.

Создаёт span `http.{METHOD} {path}` на каждый входящий HTTP-запрос,
насыщает его стандартными HTTP- и app-атрибутами и распространяет
контекст через `traceparent` header (W3C Trace Context).

Ключевые атрибуты span:
    * http.method / http.url / http.route / http.status_code
    * http.user_agent / http.client_ip
    * app.tenant_id (из `X-Tenant-ID` или `current_tenant()`)
    * correlation.id / request.id (из `request.state`)
    * app.route_id — если известен из DSL match

Интеграция с распределённой трассировкой:
    * Входящий `traceparent` → continue span (через `TraceContextTextMapPropagator`).
    * Outbound — inject актуальный `traceparent` в response headers,
      чтобы downstream hops (webhook consumers, SSE clients) видели
      единый trace.

Фаза: IL-OBS1 (ADR-032).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

__all__ = ("OtelMiddleware",)

logger = logging.getLogger("infra.otel.middleware")


class OtelMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware для auto-tracing HTTP-запросов через OpenTelemetry.

    Создаёт корневой span на каждый HTTP-запрос; если во входящих заголовках
    присутствует `traceparent`, присоединяется к существующему trace. Атрибуты
    span охватывают HTTP-слой и приложенческий контекст (tenant, correlation,
    route_id). В response injecting-ся actual `traceparent` — это делает
    дальнейшие hop-ы частью того же trace.

    Полностью отказоустойчиво: если OpenTelemetry SDK не установлен или не
    сконфигурирован (`OTEL_EXPORTER_OTLP_ENDPOINT` не задан) — middleware
    работает как no-op, не ломая pipeline.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Инициализирует middleware и пытается загрузить OTEL-зависимости.

        Args:
            app: ASGI-приложение, к которому применяется middleware.
        """
        super().__init__(app)
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
        except Exception as exc:  # pragma: no cover — defensive
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

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Оборачивает обработку запроса в OTEL span.

        Args:
            request: Входящий HTTP-запрос.
            call_next: Следующий middleware/обработчик.

        Returns:
            HTTP-ответ с заголовком `traceparent` (если tracing активен).
        """
        if self._tracer is None:
            return await call_next(request)

        ctx = self._extract_context(request)
        span_name = f"http.{request.method.lower()} {request.url.path}"
        attributes = self._build_attributes(request)

        try:
            from opentelemetry import trace  # noqa: F401  # availability probe
            from opentelemetry.trace import SpanKind
        except ImportError:
            return await call_next(request)

        span_cm = self._tracer.start_as_current_span(
            span_name, context=ctx, kind=SpanKind.SERVER, attributes=attributes
        )

        try:
            with span_cm as span:
                response = await self._process(request, call_next, span)
                self._inject_traceparent(response)
                return response
        except Exception:
            # Ошибка уже размечена в _process — пробрасываем
            raise

    async def _process(
        self, request: Request, call_next: RequestResponseEndpoint, span: Any
    ) -> Response:
        """Выполняет call_next, помечая span при ошибке."""
        try:
            response = await call_next(request)
        except Exception as exc:
            self._mark_error(span, exc)
            raise
        else:
            try:
                span.set_attribute("http.status_code", response.status_code)
                if response.status_code >= 500:
                    self._mark_error(span, RuntimeError(f"HTTP {response.status_code}"))
            except AttributeError, TypeError:
                pass

            # Post-response context: route_id/tenant могут быть выставлены
            # downstream middleware / endpoint handler-ом → добираем после.
            route_id = getattr(request.state, "route_id", None)
            if route_id:
                try:
                    span.set_attribute("app.route_id", str(route_id))
                except AttributeError, TypeError:
                    pass
            return response

    def _extract_context(self, request: Request) -> Any:
        """Извлекает W3C trace-context из входящих заголовков (если есть)."""
        if self._propagator is None:
            return None
        try:
            carrier = {k.lower(): v for k, v in request.headers.items()}
            return self._propagator.extract(carrier=carrier)
        except Exception:  # pragma: no cover
            return None

    def _inject_traceparent(self, response: Response) -> None:
        """Прокидывает актуальный `traceparent` в response headers."""
        if self._propagator is None:
            return
        carrier: dict[str, str] = {}
        try:
            self._propagator.inject(carrier)
        except Exception:  # pragma: no cover
            return
        for key, value in carrier.items():
            response.headers[key] = value

    @staticmethod
    def _build_attributes(request: Request) -> dict[str, Any]:
        """Формирует стартовый набор OTEL-атрибутов HTTP-span-а."""
        client_ip = request.client.host if request.client else ""
        user_agent = request.headers.get("user-agent", "")[:200]

        # Tenant: сначала header, потом ContextVar.
        tenant_id = request.headers.get("x-tenant-id", "")
        if not tenant_id:
            try:
                from src.core.tenancy import current_tenant

                ctx = current_tenant()
                if ctx is not None:
                    tenant_id = getattr(ctx, "tenant_id", "") or ""
            except Exception:  # noqa: BLE001 — best-effort
                tenant_id = ""

        attrs: dict[str, Any] = {
            "http.method": request.method,
            "http.url": str(request.url),
            "http.route": request.url.path,
            "http.client_ip": client_ip,
            "http.user_agent": user_agent,
        }

        correlation_id = getattr(request.state, "correlation_id", None)
        request_id = getattr(request.state, "request_id", None)
        if correlation_id:
            attrs["correlation.id"] = str(correlation_id)
        if request_id:
            attrs["request.id"] = str(request_id)
        if tenant_id:
            attrs["app.tenant_id"] = str(tenant_id)

        return attrs

    @staticmethod
    def _mark_error(span: Any, exc: BaseException) -> None:
        """Помечает span как ошибочный, учитывая несовместимость SDK версий."""
        try:
            from opentelemetry.trace import Status, StatusCode

            span.set_status(Status(StatusCode.ERROR, str(exc)[:200]))
        except Exception:  # pragma: no cover
            try:
                span.set_attribute("error", True)
            except AttributeError, TypeError:
                pass
        try:
            span.record_exception(exc)
        except AttributeError, TypeError:
            pass
