"""HTTPSink — отправка REST-запроса через ``httpx`` (Wave 3.1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.core.interfaces.sink import Sink, SinkKind, SinkResult

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
    timeout: float = 10.0
    kind: SinkKind = field(default=SinkKind.HTTP, init=False)

    async def send(self, payload: Any) -> SinkResult:
        """Отправляет ``payload`` в ``url`` указанным методом."""
        try:
            import httpx
        except ImportError:
            return SinkResult(ok=False, details={"error": "httpx not installed"})

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(
                    method=self.method,
                    url=self.url,
                    json=payload if not isinstance(payload, (bytes, str)) else None,
                    content=payload if isinstance(payload, (bytes, str)) else None,
                    headers=self.headers,
                )
        except Exception as exc:  # noqa: BLE001 — мап в SinkResult.
            return SinkResult(
                ok=False, details={"error": str(exc) or exc.__class__.__name__}
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

    async def health(self) -> bool:
        """HEAD-запрос на URL; ``True`` при 2xx/3xx/4xx (адрес отвечает)."""
        try:
            import httpx
        except ImportError:
            return False
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.head(self.url)
        except Exception:  # noqa: BLE001
            return False
        # 4xx считаем как «адрес отвечает» (метод не разрешён, и т.п.).
        return response.status_code < 500
