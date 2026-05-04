"""WebhookSink — POST на URL с опциональной HMAC-подписью (Wave 3.1).

Отличается от HTTPSink тем, что:

* подписывает payload HMAC-SHA256 если ``secret`` задан;
* добавляет canonical webhook-headers (``X-Webhook-Event``,
  ``X-Webhook-Signature``);
* всегда ``POST`` (это webhook-канал).
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Any

from src.core.interfaces.sink import Sink, SinkKind, SinkResult
from src.utilities.json_codec import dumps_bytes

__all__ = ("WebhookSink",)


@dataclass(slots=True)
class WebhookSink(Sink):
    """Sink для исходящих webhook-вызовов.

    Args:
        sink_id: Уникальный идентификатор.
        url: Целевой webhook URL.
        event: Имя события (попадает в ``X-Webhook-Event``).
        secret: HMAC-секрет (опционально). Если задан — подпись
            ``hmac.sha256(secret, body)`` ставится в ``X-Webhook-Signature``.
        timeout: Таймаут в секундах.
        extra_headers: Дополнительные заголовки.
    """

    sink_id: str
    url: str
    event: str
    secret: str | None = None
    timeout: float = 10.0
    extra_headers: dict[str, str] = field(default_factory=dict)
    kind: SinkKind = field(default=SinkKind.WEBHOOK, init=False)

    async def send(self, payload: Any) -> SinkResult:
        """Подписывает и отправляет ``payload`` на ``url``."""
        try:
            import httpx
        except ImportError:
            return SinkResult(ok=False, details={"error": "httpx not installed"})

        body_bytes = dumps_bytes(payload)
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "X-Webhook-Event": self.event,
            **self.extra_headers,
        }
        if self.secret:
            sig = hmac.new(
                self.secret.encode("utf-8"), body_bytes, hashlib.sha256
            ).hexdigest()
            headers["X-Webhook-Signature"] = sig

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.url, content=body_bytes, headers=headers
                )
        except Exception as exc:  # noqa: BLE001
            return SinkResult(
                ok=False, details={"error": str(exc) or exc.__class__.__name__}
            )

        ok = 200 <= response.status_code < 300
        return SinkResult(
            ok=ok,
            external_id=response.headers.get("x-request-id"),
            details={"status_code": response.status_code, "signed": bool(self.secret)},
        )

    async def health(self) -> bool:
        """HEAD-запрос на webhook-URL; ``True`` если адрес отвечает."""
        try:
            import httpx
        except ImportError:
            return False
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.head(self.url)
        except Exception:  # noqa: BLE001
            return False
        return response.status_code < 500
