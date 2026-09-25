"""Per-processor health checks (Kafka SR, Temporal, Vault, ClickHouse, Redis, NATS, Graylog).

W9 P2-13 Phase 4 (cycle 153): извлечено из ``services/ops/health.py``
(609 LOC god-module).

Default processor-checks, регистрируются при startup через
``get_processor_health_service()``. Каждая check возвращает
``ProcessorHealthResult`` с ok/reason/latency_ms.

Back-compat: ``services/ops/health.py`` (file) продолжает re-export через
thin ``__init__.py`` shim (см. ADR-0329).
"""

from __future__ import annotations

import asyncio
import time

from src.backend.core.async_utils.safe_wait import safe_wait_for
from src.backend.services.ops.health._http import _http_get, _tcp_connect
from src.backend.services.ops.health._types import ProcessorHealthResult


async def _check_kafka_schema_registry() -> ProcessorHealthResult:
    """Проверка доступности Kafka schema-registry.

    Default-реализация — best-effort через lazy import faststream/confluent.
    Возвращает ``ok=False`` если SDK не установлен.
    """
    start = time.monotonic()
    try:
        from src.backend.core.config.settings import settings

        registry_url = getattr(settings.queue, "schema_registry_url", None)
        if not registry_url:
            return ProcessorHealthResult(
                processor_name="kafka_schema_registry",
                ok=False,
                reason="schema_registry_url не настроен",
                latency_ms=(time.monotonic() - start) * 1000,
            )
        code, _ = await safe_wait_for(  # type: ignore[misc]  # reraise=True
            _http_get(f"{registry_url.rstrip('/')}/subjects"),
            timeout=5.0,
            operation="kafka_schema_registry",
        )
        if code >= 300:
            return ProcessorHealthResult(
                processor_name="kafka_schema_registry",
                ok=False,
                reason=f"HTTP {code}",
                latency_ms=(time.monotonic() - start) * 1000,
            )
        return ProcessorHealthResult(
            processor_name="kafka_schema_registry",
            ok=True,
            reason="healthy",
            latency_ms=(time.monotonic() - start) * 1000,
        )
    except Exception as exc:
        return ProcessorHealthResult(
            processor_name="kafka_schema_registry",
            ok=False,
            reason=f"check failed: {type(exc).__name__}: {exc}",
            latency_ms=(time.monotonic() - start) * 1000,
        )


async def _check_temporal_server() -> ProcessorHealthResult:
    """Проверка доступности Temporal server."""
    start = time.monotonic()
    try:
        from src.backend.core.config.settings import settings

        temporal_host = getattr(getattr(settings, "workflow", None), "host", None)
        if not temporal_host:
            return ProcessorHealthResult(
                processor_name="temporal_server",
                ok=False,
                reason="temporal.host не настроен",
                latency_ms=(time.monotonic() - start) * 1000,
            )
        host, _, port_str = temporal_host.rpartition(":")
        if not host:
            host = temporal_host
            port = 7233
        else:
            port = int(port_str)
        await safe_wait_for(
            _tcp_connect(host, port), timeout=5.0, operation="temporal_server"
        )
        return ProcessorHealthResult(
            processor_name="temporal_server",
            ok=True,
            reason="healthy",
            latency_ms=(time.monotonic() - start) * 1000,
        )
    except Exception as exc:
        return ProcessorHealthResult(
            processor_name="temporal_server",
            ok=False,
            reason=f"check failed: {type(exc).__name__}: {exc}",
            latency_ms=(time.monotonic() - start) * 1000,
        )


async def _check_vault_sealed() -> ProcessorHealthResult:
    """Проверка, что Vault unsealed и доступен."""
    start = time.monotonic()
    try:
        from src.backend.core.config.settings import settings

        vault = getattr(settings, "vault", None)
        if vault is None or not getattr(vault, "enabled", False):
            return ProcessorHealthResult(
                processor_name="vault",
                ok=True,
                reason="not configured",
                latency_ms=(time.monotonic() - start) * 1000,
            )
        addr = getattr(vault, "addr", "")
        if not addr:
            return ProcessorHealthResult(
                processor_name="vault",
                ok=True,
                reason="not configured",
                latency_ms=(time.monotonic() - start) * 1000,
            )
        code, text = await asyncio.wait_for(
            _http_get(f"{addr.rstrip('/')}/v1/sys/seal-status"), timeout=5.0
        )
        if code != 200:
            return ProcessorHealthResult(
                processor_name="vault",
                ok=False,
                reason=f"HTTP {code}",
                latency_ms=(time.monotonic() - start) * 1000,
            )
        import json

        data = json.loads(text)
        if data.get("sealed", True):
            return ProcessorHealthResult(
                processor_name="vault",
                ok=False,
                reason="vault is sealed",
                latency_ms=(time.monotonic() - start) * 1000,
            )
        return ProcessorHealthResult(
            processor_name="vault",
            ok=True,
            reason="healthy",
            latency_ms=(time.monotonic() - start) * 1000,
        )
    except Exception as exc:
        return ProcessorHealthResult(
            processor_name="vault",
            ok=False,
            reason=f"check failed: {type(exc).__name__}: {exc}",
            latency_ms=(time.monotonic() - start) * 1000,
        )


async def _check_clickhouse() -> ProcessorHealthResult:
    """Проверка доступности ClickHouse."""
    start = time.monotonic()
    try:
        from src.backend.core.config.settings import settings

        ch = getattr(settings, "clickhouse", None)
        if ch is None or not getattr(ch, "enabled", False):
            return ProcessorHealthResult(
                processor_name="clickhouse",
                ok=True,
                reason="not configured",
                latency_ms=(time.monotonic() - start) * 1000,
            )
        host = getattr(ch, "host", "")
        port = getattr(ch, "http_port", 8123)
        if not host:
            return ProcessorHealthResult(
                processor_name="clickhouse",
                ok=True,
                reason="not configured",
                latency_ms=(time.monotonic() - start) * 1000,
            )
        code, text = await asyncio.wait_for(
            _http_get(f"http://{host}:{port}/ping"), timeout=5.0
        )
        if code != 200 or text.strip() != "Ok.":
            return ProcessorHealthResult(
                processor_name="clickhouse",
                ok=False,
                reason=f"HTTP {code}",
                latency_ms=(time.monotonic() - start) * 1000,
            )
        return ProcessorHealthResult(
            processor_name="clickhouse",
            ok=True,
            reason="healthy",
            latency_ms=(time.monotonic() - start) * 1000,
        )
    except Exception as exc:
        return ProcessorHealthResult(
            processor_name="clickhouse",
            ok=False,
            reason=f"check failed: {type(exc).__name__}: {exc}",
            latency_ms=(time.monotonic() - start) * 1000,
        )


async def _check_redis_cluster() -> ProcessorHealthResult:
    """Проверка доступности Redis cluster (через PING)."""
    start = time.monotonic()
    try:
        from src.backend.core.config.settings import settings

        redis = getattr(settings, "redis", None)
        if redis is None or not getattr(redis, "enabled", False):
            return ProcessorHealthResult(
                processor_name="redis_cluster",
                ok=True,
                reason="not configured",
                latency_ms=(time.monotonic() - start) * 1000,
            )
        host = getattr(redis, "host", "")
        port = getattr(redis, "port", 6379)
        if not host:
            return ProcessorHealthResult(
                processor_name="redis_cluster",
                ok=True,
                reason="not configured",
                latency_ms=(time.monotonic() - start) * 1000,
            )
        import redis.asyncio as aioredis

        r = aioredis.Redis(
            host=host,
            port=port,
            socket_connect_timeout=min(
                5.0, getattr(redis, "socket_connect_timeout", None) or 5.0
            ),
        )
        await asyncio.wait_for(r.ping(), timeout=5.0)
        await r.close()
        return ProcessorHealthResult(
            processor_name="redis_cluster",
            ok=True,
            reason="healthy",
            latency_ms=(time.monotonic() - start) * 1000,
        )
    except Exception as exc:
        return ProcessorHealthResult(
            processor_name="redis_cluster",
            ok=False,
            reason=f"check failed: {type(exc).__name__}: {exc}",
            latency_ms=(time.monotonic() - start) * 1000,
        )


async def _check_nats() -> ProcessorHealthResult:
    """Проверка доступности NATS."""
    start = time.monotonic()
    try:
        from src.backend.core.config.settings import settings

        nats_cfg = getattr(settings, "nats", None)
        if nats_cfg is not None:
            host = getattr(nats_cfg, "host", "")
            port = getattr(nats_cfg, "port", 4222)
        else:
            # Попробуем вытащить URL из очереди, если broker_url начинается с nats://
            queue_cfg = getattr(settings, "queue", None)
            broker_url = getattr(queue_cfg, "broker_url", "")
            if isinstance(broker_url, str) and broker_url.startswith("nats://"):
                from urllib.parse import urlparse

                parsed = urlparse(broker_url)
                host = parsed.hostname or ""
                port = parsed.port or 4222
            else:
                host = ""
                port = 4222
        if not host:
            return ProcessorHealthResult(
                processor_name="nats",
                ok=True,
                reason="not configured",
                latency_ms=(time.monotonic() - start) * 1000,
            )
        await asyncio.wait_for(_tcp_connect(host, port), timeout=5.0)
        return ProcessorHealthResult(
            processor_name="nats",
            ok=True,
            reason="healthy",
            latency_ms=(time.monotonic() - start) * 1000,
        )
    except Exception as exc:
        return ProcessorHealthResult(
            processor_name="nats",
            ok=False,
            reason=f"check failed: {type(exc).__name__}: {exc}",
            latency_ms=(time.monotonic() - start) * 1000,
        )


async def _check_graylog() -> ProcessorHealthResult:
    """Проверка доступности Graylog (через TCP-ping или HTTP-API)."""
    start = time.monotonic()
    try:
        from src.backend.core.config.settings import settings

        log_cfg = getattr(settings, "logging", None)
        if log_cfg is None:
            return ProcessorHealthResult(
                processor_name="graylog",
                ok=True,
                reason="not configured",
                latency_ms=(time.monotonic() - start) * 1000,
            )
        host = getattr(log_cfg, "host", "")
        if not host:
            return ProcessorHealthResult(
                processor_name="graylog",
                ok=True,
                reason="not configured",
                latency_ms=(time.monotonic() - start) * 1000,
            )
        base_url = getattr(log_cfg, "base_url", None)
        if not base_url:
            port = getattr(log_cfg, "port", 9000)
            use_tls = getattr(log_cfg, "use_tls", False)
            scheme = "https" if use_tls else "http"
            base_url = f"{scheme}://{host}:{port}"
        code, _ = await asyncio.wait_for(
            _http_get(f"{base_url.rstrip('/')}/api/system"), timeout=5.0
        )
        if code >= 300:
            return ProcessorHealthResult(
                processor_name="graylog",
                ok=False,
                reason=f"HTTP {code}",
                latency_ms=(time.monotonic() - start) * 1000,
            )
        return ProcessorHealthResult(
            processor_name="graylog",
            ok=True,
            reason="healthy",
            latency_ms=(time.monotonic() - start) * 1000,
        )
    except Exception as exc:
        return ProcessorHealthResult(
            processor_name="graylog",
            ok=False,
            reason=f"check failed: {type(exc).__name__}: {exc}",
            latency_ms=(time.monotonic() - start) * 1000,
        )


def _is_strict_mode() -> bool:
    """Проверить feature-flag processor_health_checks_strict."""
    try:
        from src.backend.core.config.features import feature_flags

        return feature_flags.processor_health_checks_strict
    except ImportError, AttributeError:
        return False
