"""Prometheus metrics для DSL engine и инфраструктуры.

D11 (S17 K2-W2 sweep):
    Все 17 ранее inline-метрик (``Counter(...)`` / ``Histogram(...)`` /
    ``Gauge(...)``) переведены на единый :data:`metrics_registry`
    (см. :mod:`infrastructure.observability.metrics_registry`).
    Регистрация выполняется один раз при импорте модуля; повторный
    импорт безопасен — :class:`MetricsRegistry` idempotent и возвращает
    тот же instance без ``DuplicatedTimeSeries``.

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

from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.middleware import ProcessorMiddleware
from src.backend.core.logging import get_logger
from src.backend.infrastructure.observability.metrics_registry import metrics_registry

__all__ = (
    "PrometheusMetricsMiddleware",
    "get_dsl_metrics",
    "record_ai_semantic_cache_hit",
    "record_ai_semantic_cache_miss",
    "record_ai_token_usage",
    "record_antivirus_cache_hit",
    "record_antivirus_cache_miss",
    "record_antivirus_scan",
    "record_cache_hit",
    "record_cache_miss",
    "record_circuit_breaker_state",
    "record_express_command_received",
    "record_express_delivery_latency",
    "record_express_message_sent",
    "record_pipeline_execution",
    "record_pool_metric",
    "record_queue_consumer_lag",
    "record_queue_dlq_depth",
)

logger = get_logger(__name__)

# ── DSL pipeline / processor ────────────────────────────────────────────
_processor_histogram = metrics_registry.histogram(
    "dsl_processor_duration_seconds",
    "DSL processor execution duration",
    labels=("route_id", "processor_type"),
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 30.0),
)
_pipeline_counter = metrics_registry.counter(
    "dsl_pipeline_total", "DSL pipeline executions", labels=("route_id", "status")
)

# ── Resilience / pools ──────────────────────────────────────────────────
_breaker_gauge = metrics_registry.gauge(
    "circuit_breaker_state",
    "Circuit breaker state (0=closed, 1=half_open, 2=open)",
    labels=("name",),
)
_pool_gauge = metrics_registry.gauge(
    "connection_pool_utilization",
    "Connection pool active connections",
    labels=("pool_name", "metric"),
)

# ── Cache ───────────────────────────────────────────────────────────────
_cache_hits_counter = metrics_registry.counter(
    "cache_hits_total", "Cache hits", labels=("backend", "key_prefix")
)
_cache_misses_counter = metrics_registry.counter(
    "cache_misses_total", "Cache misses", labels=("backend", "key_prefix")
)

# ── Express ─────────────────────────────────────────────────────────────
_express_sent_counter = metrics_registry.counter(
    "express_messages_sent_total", "Express messages sent", labels=("bot", "status")
)
_express_received_counter = metrics_registry.counter(
    "express_commands_received_total",
    "Express commands received from users",
    labels=("bot", "command"),
)
_express_delivery_histogram = metrics_registry.histogram(
    "express_delivery_latency_seconds",
    "Express message delivery latency (read_at - sent_at)",
    labels=("bot",),
    buckets=(0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0),
)

# ── AI ──────────────────────────────────────────────────────────────────
_ai_tokens_counter = metrics_registry.counter(
    "ai_token_usage_total",
    "AI provider token usage",
    labels=("provider", "model", "kind"),  # kind = prompt|completion
)
_ai_semantic_hits_counter = metrics_registry.counter(
    "ai_semantic_cache_hits_total", "AI semantic cache hits", labels=("model",)
)
_ai_semantic_misses_counter = metrics_registry.counter(
    "ai_semantic_cache_misses_total", "AI semantic cache misses", labels=("model",)
)

# ── Antivirus ───────────────────────────────────────────────────────────
_antivirus_scan_histogram = metrics_registry.histogram(
    "antivirus_scan_duration_seconds",
    "Antivirus scan duration",
    labels=("backend",),
    buckets=(0.001, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0),
)
_antivirus_hits_counter = metrics_registry.counter(
    "antivirus_cache_hits_total", "Antivirus hash-cache hits"
)
_antivirus_misses_counter = metrics_registry.counter(
    "antivirus_cache_misses_total", "Antivirus hash-cache misses"
)

# ── Queue ───────────────────────────────────────────────────────────────
_queue_lag_gauge = metrics_registry.gauge(
    "queue_consumer_lag",
    "Queue consumer lag (messages behind head)",
    labels=("queue", "consumer_group"),
)
_queue_dlq_gauge = metrics_registry.gauge(
    "queue_dlq_depth", "Dead letter queue depth", labels=("queue",)
)


def get_dsl_metrics() -> dict[str, Any]:
    """Возвращает основные DSL-метрики (для admin/health endpoint)."""
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
        """Pre-execution hook: метрики регистрируются at-import, no-op."""
        # Метрики уже зарегистрированы при импорте модуля — no-op hook.
        return None

    async def after(
        self,
        processor_name: str,
        exchange: Exchange[Any],
        context: ExecutionContext,
        error: Exception | None,
        duration_ms: float,
    ) -> None:
        """Post-execution hook: наблюдает latency в ``_processor_histogram``."""
        _processor_histogram.labels(
            route_id=context.route_id or "unknown", processor_type=processor_name
        ).observe(duration_ms / 1000.0)


def record_pipeline_execution(route_id: str, status: str) -> None:
    """Инкрементирует счётчик выполнений pipeline по route_id+status."""
    _pipeline_counter.labels(route_id=route_id, status=status).inc()


def record_circuit_breaker_state(name: str, state_value: int) -> None:
    """Устанавливает gauge состояния circuit breaker'а по имени."""
    _breaker_gauge.labels(name=name).set(state_value)


def record_pool_metric(pool_name: str, metric: str, value: float) -> None:
    """Обновляет gauge метрики connection pool'а (active/idle/used)."""
    _pool_gauge.labels(pool_name=pool_name, metric=metric).set(value)


def record_cache_hit(backend: str, key_prefix: str = "") -> None:
    """Инкрементирует счётчик cache HIT'ов по backend+key_prefix."""
    _cache_hits_counter.labels(backend=backend, key_prefix=key_prefix).inc()


def record_cache_miss(backend: str, key_prefix: str = "") -> None:
    """Инкрементирует счётчик cache MISS'ов по backend+key_prefix."""
    _cache_misses_counter.labels(backend=backend, key_prefix=key_prefix).inc()


def record_express_message_sent(bot: str, status: str = "ok") -> None:
    """Инкрементирует счётчик отправленных Express-сообщений по bot+status."""
    _express_sent_counter.labels(bot=bot, status=status).inc()


def record_express_command_received(bot: str, command: str) -> None:
    """Инкрементирует счётчик полученных Express-команд по bot+command."""
    _express_received_counter.labels(bot=bot, command=command).inc()


def record_express_delivery_latency(bot: str, latency_seconds: float) -> None:
    """Наблюдает latency доставки Express-сообщений по bot."""
    _express_delivery_histogram.labels(bot=bot).observe(latency_seconds)


def record_ai_token_usage(provider: str, model: str, kind: str, tokens: int) -> None:
    """Регистрирует расход токенов AI-провайдера.

    Args:
        provider: openai | anthropic | ollama | yandex | ...
        model: имя модели.
        kind: ``prompt`` | ``completion``.
        tokens: количество токенов.
    """
    _ai_tokens_counter.labels(provider=provider, model=model, kind=kind).inc(tokens)


def record_ai_semantic_cache_hit(model: str) -> None:
    """Инкрементирует счётчик semantic-cache HIT'ов по model."""
    _ai_semantic_hits_counter.labels(model=model).inc()


def record_ai_semantic_cache_miss(model: str) -> None:
    """Инкрементирует счётчик semantic-cache MISS'ов по model."""
    _ai_semantic_misses_counter.labels(model=model).inc()


def record_antivirus_scan(backend: str, duration_seconds: float) -> None:
    """Наблюдает latency антивирусного сканирования по backend."""
    _antivirus_scan_histogram.labels(backend=backend).observe(duration_seconds)


def record_antivirus_cache_hit() -> None:
    """Инкрементирует глобальный счётчик hash-cache HIT'ов антивируса."""
    _antivirus_hits_counter.inc()


def record_antivirus_cache_miss() -> None:
    """Инкрементирует глобальный счётчик hash-cache MISS'ов антивируса."""
    _antivirus_misses_counter.inc()


def record_queue_consumer_lag(queue: str, consumer_group: str, lag: int) -> None:
    """Устанавливает gauge lag'а consumer'а очереди по queue+group."""
    _queue_lag_gauge.labels(queue=queue, consumer_group=consumer_group).set(lag)


def record_queue_dlq_depth(queue: str, depth: int) -> None:
    """Устанавливает gauge глубины DLQ очереди по queue."""
    _queue_dlq_gauge.labels(queue=queue).set(depth)
