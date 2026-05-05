"""Prometheus metrics для DSL engine и инфраструктуры (Wave 5.2).

Расширенный набор метрик:
- DSL: processor latency, pipeline executions.
- Infrastructure: circuit breakers, connection pools.
- Cache: hit ratio, memory usage.
- Queue: consumer lag, DLQ depth.
- Express: messages sent/received, delivery latency.
- AI: token usage, semantic cache hit ratio.
- Antivirus: scan latency, hash cache hit ratio.
"""

from __future__ import annotations

import logging
from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.middleware import ProcessorMiddleware

__all__ = (
    "PrometheusMetricsMiddleware",
    "get_dsl_metrics",
    "record_express_message_sent",
    "record_express_command_received",
    "record_express_delivery_latency",
    "record_cache_hit",
    "record_cache_miss",
    "record_ai_token_usage",
    "record_ai_semantic_cache_hit",
    "record_ai_semantic_cache_miss",
    "record_antivirus_scan",
    "record_antivirus_cache_hit",
    "record_antivirus_cache_miss",
    "record_queue_consumer_lag",
    "record_queue_dlq_depth",
)

logger = logging.getLogger(__name__)

_metrics_initialized = False
_processor_histogram = None
_pipeline_counter = None
_breaker_gauge = None
_pool_gauge = None
# Wave 5.2 — расширенный набор
_cache_hits_counter = None
_cache_misses_counter = None
_express_sent_counter = None
_express_received_counter = None
_express_delivery_histogram = None
_ai_tokens_counter = None
_ai_semantic_hits_counter = None
_ai_semantic_misses_counter = None
_antivirus_scan_histogram = None
_antivirus_hits_counter = None
_antivirus_misses_counter = None
_queue_lag_gauge = None
_queue_dlq_gauge = None


def _ensure_metrics():
    global \
        _metrics_initialized, \
        _processor_histogram, \
        _pipeline_counter, \
        _breaker_gauge, \
        _pool_gauge, \
        _cache_hits_counter, \
        _cache_misses_counter, \
        _express_sent_counter, \
        _express_received_counter, \
        _express_delivery_histogram, \
        _ai_tokens_counter, \
        _ai_semantic_hits_counter, \
        _ai_semantic_misses_counter, \
        _antivirus_scan_histogram, \
        _antivirus_hits_counter, \
        _antivirus_misses_counter, \
        _queue_lag_gauge, \
        _queue_dlq_gauge
    if _metrics_initialized:
        return
    try:
        from prometheus_client import Counter, Gauge, Histogram

        _processor_histogram = Histogram(
            "dsl_processor_duration_seconds",
            "DSL processor execution duration",
            labelnames=["route_id", "processor_type"],
            buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 30.0),
        )
        _pipeline_counter = Counter(
            "dsl_pipeline_total",
            "DSL pipeline executions",
            labelnames=["route_id", "status"],
        )
        _breaker_gauge = Gauge(
            "circuit_breaker_state",
            "Circuit breaker state (0=closed, 1=half_open, 2=open)",
            labelnames=["name"],
        )
        _pool_gauge = Gauge(
            "connection_pool_utilization",
            "Connection pool active connections",
            labelnames=["pool_name", "metric"],
        )
        # Cache (Wave 5.2)
        _cache_hits_counter = Counter(
            "cache_hits_total", "Cache hits", labelnames=["backend", "key_prefix"]
        )
        _cache_misses_counter = Counter(
            "cache_misses_total", "Cache misses", labelnames=["backend", "key_prefix"]
        )
        # Express (Wave 5.2)
        _express_sent_counter = Counter(
            "express_messages_sent_total",
            "Express messages sent",
            labelnames=["bot", "status"],
        )
        _express_received_counter = Counter(
            "express_commands_received_total",
            "Express commands received from users",
            labelnames=["bot", "command"],
        )
        _express_delivery_histogram = Histogram(
            "express_delivery_latency_seconds",
            "Express message delivery latency (read_at - sent_at)",
            labelnames=["bot"],
            buckets=(0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0),
        )
        # AI (Wave 5.2)
        _ai_tokens_counter = Counter(
            "ai_token_usage_total",
            "AI provider token usage",
            labelnames=["provider", "model", "kind"],  # kind = prompt|completion
        )
        _ai_semantic_hits_counter = Counter(
            "ai_semantic_cache_hits_total",
            "AI semantic cache hits",
            labelnames=["model"],
        )
        _ai_semantic_misses_counter = Counter(
            "ai_semantic_cache_misses_total",
            "AI semantic cache misses",
            labelnames=["model"],
        )
        # Antivirus (Wave 5.2)
        _antivirus_scan_histogram = Histogram(
            "antivirus_scan_duration_seconds",
            "Antivirus scan duration",
            labelnames=["backend"],
            buckets=(0.001, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0),
        )
        _antivirus_hits_counter = Counter(
            "antivirus_cache_hits_total", "Antivirus hash-cache hits"
        )
        _antivirus_misses_counter = Counter(
            "antivirus_cache_misses_total", "Antivirus hash-cache misses"
        )
        # Queue (Wave 5.2)
        _queue_lag_gauge = Gauge(
            "queue_consumer_lag",
            "Queue consumer lag (messages behind head)",
            labelnames=["queue", "consumer_group"],
        )
        _queue_dlq_gauge = Gauge(
            "queue_dlq_depth", "Dead letter queue depth", labelnames=["queue"]
        )
        _metrics_initialized = True
    except ImportError:
        _metrics_initialized = True


def get_dsl_metrics() -> dict[str, Any]:
    return {
        "processor_histogram": _processor_histogram,
        "pipeline_counter": _pipeline_counter,
        "breaker_gauge": _breaker_gauge,
        "pool_gauge": _pool_gauge,
    }


class PrometheusMetricsMiddleware(ProcessorMiddleware):
    """Отправляет метрики DSL-процессоров в Prometheus."""

    async def before(
        self, processor_name: str, exchange: Exchange[Any], context: ExecutionContext
    ) -> None:
        _ensure_metrics()

    async def after(
        self,
        processor_name: str,
        exchange: Exchange[Any],
        context: ExecutionContext,
        error: Exception | None,
        duration_ms: float,
    ) -> None:
        if _processor_histogram is not None:
            _processor_histogram.labels(
                route_id=context.route_id or "unknown", processor_type=processor_name
            ).observe(duration_ms / 1000.0)


def record_pipeline_execution(route_id: str, status: str) -> None:
    _ensure_metrics()
    if _pipeline_counter is not None:
        _pipeline_counter.labels(route_id=route_id, status=status).inc()


def record_circuit_breaker_state(name: str, state_value: int) -> None:
    _ensure_metrics()
    if _breaker_gauge is not None:
        _breaker_gauge.labels(name=name).set(state_value)


def record_pool_metric(pool_name: str, metric: str, value: float) -> None:
    _ensure_metrics()
    if _pool_gauge is not None:
        _pool_gauge.labels(pool_name=pool_name, metric=metric).set(value)


# --- Wave 5.2 рекордеры ---


def record_cache_hit(backend: str, key_prefix: str = "") -> None:
    _ensure_metrics()
    if _cache_hits_counter is not None:
        _cache_hits_counter.labels(backend=backend, key_prefix=key_prefix).inc()


def record_cache_miss(backend: str, key_prefix: str = "") -> None:
    _ensure_metrics()
    if _cache_misses_counter is not None:
        _cache_misses_counter.labels(backend=backend, key_prefix=key_prefix).inc()


def record_express_message_sent(bot: str, status: str = "ok") -> None:
    _ensure_metrics()
    if _express_sent_counter is not None:
        _express_sent_counter.labels(bot=bot, status=status).inc()


def record_express_command_received(bot: str, command: str) -> None:
    _ensure_metrics()
    if _express_received_counter is not None:
        _express_received_counter.labels(bot=bot, command=command).inc()


def record_express_delivery_latency(bot: str, latency_seconds: float) -> None:
    _ensure_metrics()
    if _express_delivery_histogram is not None:
        _express_delivery_histogram.labels(bot=bot).observe(latency_seconds)


def record_ai_token_usage(provider: str, model: str, kind: str, tokens: int) -> None:
    """Регистрирует расход токенов AI-провайдера.

    Args:
        provider: openai | anthropic | ollama | yandex | ...
        model: имя модели.
        kind: ``prompt`` | ``completion``.
        tokens: количество токенов.
    """
    _ensure_metrics()
    if _ai_tokens_counter is not None:
        _ai_tokens_counter.labels(provider=provider, model=model, kind=kind).inc(tokens)


def record_ai_semantic_cache_hit(model: str) -> None:
    _ensure_metrics()
    if _ai_semantic_hits_counter is not None:
        _ai_semantic_hits_counter.labels(model=model).inc()


def record_ai_semantic_cache_miss(model: str) -> None:
    _ensure_metrics()
    if _ai_semantic_misses_counter is not None:
        _ai_semantic_misses_counter.labels(model=model).inc()


def record_antivirus_scan(backend: str, duration_seconds: float) -> None:
    _ensure_metrics()
    if _antivirus_scan_histogram is not None:
        _antivirus_scan_histogram.labels(backend=backend).observe(duration_seconds)


def record_antivirus_cache_hit() -> None:
    _ensure_metrics()
    if _antivirus_hits_counter is not None:
        _antivirus_hits_counter.inc()


def record_antivirus_cache_miss() -> None:
    _ensure_metrics()
    if _antivirus_misses_counter is not None:
        _antivirus_misses_counter.inc()


def record_queue_consumer_lag(queue: str, consumer_group: str, lag: int) -> None:
    _ensure_metrics()
    if _queue_lag_gauge is not None:
        _queue_lag_gauge.labels(queue=queue, consumer_group=consumer_group).set(lag)


def record_queue_dlq_depth(queue: str, depth: int) -> None:
    _ensure_metrics()
    if _queue_dlq_gauge is not None:
        _queue_dlq_gauge.labels(queue=queue).set(depth)
