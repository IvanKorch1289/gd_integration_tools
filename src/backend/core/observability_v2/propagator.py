"""Correlation propagator — extract/inject через headers/msg metadata."""

from __future__ import annotations

from typing import Any

from src.backend.core.observability_v2.context import SemanticContext

__all__ = ("CorrelationPropagator", "TraceContextCarrier")


class TraceContextCarrier:
    """W3C Trace Context + custom correlation keys.

    Headers format:
    - traceparent: ``00-{trace_id}-{span_id}-{flags}``
    - tracestate: vendor-specific (не используем здесь).
    - X-Correlation-ID: correlation_id.
    - X-Tenant-ID: tenant_id.
    - X-Route-ID: route_id.
    - X-Business-Keys: comma-separated key=value pairs.
    """

    TRACEPARENT_HEADER = "traceparent"
    CORRELATION_ID_HEADER = "X-Correlation-ID"
    TENANT_ID_HEADER = "X-Tenant-ID"
    ROUTE_ID_HEADER = "X-Route-ID"
    BUSINESS_KEYS_HEADER = "X-Business-Keys"

    @staticmethod
    def inject(context: SemanticContext) -> dict[str, str]:
        """Inject context → headers dict."""
        headers: dict[str, str] = {}
        if context.trace_id and context.span_id:
            # W3C Trace Context format: version-trace_id-span_id-flags.
            headers[TraceContextCarrier.TRACEPARENT_HEADER] = (
                f"00-{context.trace_id}-{context.span_id}-01"
            )
        if context.correlation_id:
            headers[TraceContextCarrier.CORRELATION_ID_HEADER] = (
                context.correlation_id
            )
        if context.tenant_id:
            headers[TraceContextCarrier.TENANT_ID_HEADER] = context.tenant_id
        if context.route_id:
            headers[TraceContextCarrier.ROUTE_ID_HEADER] = context.route_id
        if context.business_keys:
            keys_str = ",".join(
                f"{k}={v}" for k, v in context.business_keys.items()
            )
            headers[TraceContextCarrier.BUSINESS_KEYS_HEADER] = keys_str
        return headers

    @staticmethod
    def extract(headers: dict[str, str]) -> SemanticContext:
        """Extract context from headers."""
        trace_id = ""
        span_id = ""
        traceparent = headers.get(TraceContextCarrier.TRACEPARENT_HEADER, "")
        if traceparent:
            parts = traceparent.split("-")
            if len(parts) >= 3:
                trace_id = parts[1]
                span_id = parts[2]

        business_keys: dict[str, str] = {}
        keys_str = headers.get(TraceContextCarrier.BUSINESS_KEYS_HEADER, "")
        if keys_str:
            for pair in keys_str.split(","):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    business_keys[k.strip()] = v.strip()

        return SemanticContext(
            trace_id=trace_id,
            span_id=span_id,
            correlation_id=headers.get(
                TraceContextCarrier.CORRELATION_ID_HEADER, ""
            ),
            tenant_id=headers.get(TraceContextCarrier.TENANT_ID_HEADER, ""),
            route_id=headers.get(TraceContextCarrier.ROUTE_ID_HEADER, ""),
            business_keys=business_keys,
        )


class CorrelationPropagator:
    """Unified propagator (HTTP + MQ + DB).

    Использует :class:`TraceContextCarrier` для HTTP headers и
    адаптеры для других транспортов.
    """

    @staticmethod
    def inject_to_headers(context: SemanticContext) -> dict[str, str]:
        return TraceContextCarrier.inject(context)

    @staticmethod
    def extract_from_headers(headers: dict[str, str]) -> SemanticContext:
        return TraceContextCarrier.extract(headers)

    @staticmethod
    def inject_to_metadata(context: SemanticContext) -> dict[str, Any]:
        """Inject для MQ message metadata (Kafka, Rabbit, etc.)."""
        return context.to_dict()

    @staticmethod
    def extract_from_metadata(
        metadata: dict[str, Any]
    ) -> SemanticContext:
        """Extract из MQ message metadata."""
        if not metadata:
            return SemanticContext()
        return SemanticContext.from_dict(metadata)
