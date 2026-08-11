"""HTTPSink — отправка REST-запроса через ``httpx`` (Wave 3.1)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from src.backend.core.interfaces.sink import Sink, SinkKind, SinkResult
from src.backend.core.resilience.connector_breaker import with_breaker
from src.backend.core.resilience.retry import with_retry
from src.backend.core.security.connector_auth import require_capability
from src.backend.infrastructure.clients.base_connector import HealthResult
from src.backend.infrastructure.security.connector_rate_limiter import (
    get_connector_rate_limiter,
)
from src.backend.infrastructure.sinks._timeouts import DEFAULT_SINK_TIMEOUT_S

__all__ = ("HttpSink",)


@dataclass(slots=True)
class HttpSink(Sink):
    """REST sink: POST/PUT/PATCH/DELETE на заданный URL.

    Args:
        sink_id: Уникальный идентификатор в реестре.
        url: Целевой URL.
        method: HTTP-метод (``POST`` по умолчанию).
        headers: Заголовки запроса (например, авторизация).
        timeout: Таймаут в секундах.

    Behaviour:
        * При HTTP 2xx — ``SinkResult(ok=True, external_id=<X-Request-Id>?,
          details={"status_code": ..., "elapsed_ms": ...})``.
        * При HTTP 4xx/5xx или сетевой ошибке —
          ``SinkResult(ok=False, details={"error": ..., "status_code": ...})``.

    """

    sink_id: str
    url: str
    method: str = "POST"
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = DEFAULT_SINK_TIMEOUT_S  # Cycle 12: externalized to sinks/_timeouts
    kind: SinkKind = field(default=SinkKind.HTTP, init=False)

    @with_breaker("http_sink")
    @with_retry(max_attempts=3,
        retry_on=(ConnectionError, TimeoutError, OSError))
    @require_capability("http.send", action="write")
    async def send(self, payload: Any) -> SinkResult:
        """Отправляет ``payload`` в ``url`` указанным методом."""
        # S1: per-connector rate limit (100/s).
        limiter = get_connector_rate_limiter()
        limiter.register(f"{self.sink_id}_{self.kind}", "100/s", 100)
        await limiter.check(f"{self.sink_id}_{self.kind}")

        try:
            import httpx

            from src.backend.core.net import (
                OutboundHttpClient,
            )
        except ImportError:
            return SinkResult(ok=False, details={"error": "httpx not installed"})

        try:
            async with OutboundHttpClient(
                timeout=httpx.Timeout(self.timeout),
            ) as client:
                response = await client.request(
                    method=self.method,
                    url=self.url,
                    json=payload if not isinstance(payload, (bytes, str)) else None,
                    content=payload if isinstance(payload, (bytes, str)) else None,
                    headers=self.headers,
                )
        except Exception as exc:
            return SinkResult(
                ok=False, details={"error": str(exc) or exc.__class__.__name__},
            )

        ok = 200 <= response.status_code < 300
        return SinkResult(
            ok=ok,
            external_id=response.headers.get("x-request-id"),
            details={
                "status_code": response.status_code,
                "elapsed_ms": int(response.elapsed.total_seconds() * 1000),
            },
        )

    async def health(self, mode: str = "fast") -> HealthResult:
        """HEAD-запрос на URL; ``ok`` при 2xx/3xx/4xx (адрес отвечает)."""
        try:
            import httpx

            from src.backend.core.net import (
                OutboundHttpClient,
            )
        except ImportError:
            return HealthResult.failed(error="httpx not installed", mode=mode)
        start = time.perf_counter()
        try:
            async with OutboundHttpClient(
                timeout=httpx.Timeout(self.timeout),
            ) as client:
                # ``HEAD`` через ``request`` — ``OutboundHttpClient`` не
                # имеет shortcut'а ``head``, request совместим со всеми
                # методами + поддерживает WAF-проверку.
                response = await client.request("HEAD", self.url)
            latency_ms = (time.perf_counter() - start) * 1000.0
            # 4xx считаем как «адрес отвечает» (метод не разрешён, и т.п.).
            if response.status_code < 500:
                return HealthResult.ok(
                    latency_ms=latency_ms,
                    mode=mode,
                    status_code=response.status_code,
                )
            return HealthResult.failed(
                error=f"HTTP {response.status_code}",
                mode=mode,
                latency_ms=latency_ms,
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000.0
            return HealthResult.failed(
                error=f"{type(exc).__name__}: {exc}", mode=mode, latency_ms=latency_ms,
            )
