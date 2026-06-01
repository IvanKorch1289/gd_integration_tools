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

from src.backend.core.interfaces.sink import Sink, SinkKind, SinkResult
from src.backend.dsl.codec.json import dumps_bytes

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
        """Подписывает и отправляет ``payload`` на ``url``.

        S21 W5: при включённом ``webhook_resilience_policy_enabled`` и
        наличии глобальной :class:`RPACallPolicy` — POST оборачивается через
        ``policy.call(...)`` (retry + CB + DLQ). При выключении/отсутствии
        policy поведение остаётся прежним (legacy ad-hoc try/except).
        """
        try:
            import httpx

            from src.backend.core.net import OutboundHttpClient
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

        async def _do_post() -> Any:
            async with OutboundHttpClient(
                timeout=httpx.Timeout(self.timeout)
            ) as client:
                resp = await client.post(self.url, content=body_bytes, headers=headers)
            # 5xx — поднимаем для retry policy
            if 500 <= resp.status_code < 600:
                raise httpx.HTTPStatusError(
                    f"upstream 5xx: {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )
            return resp

        try:
            from src.backend.core.config.features import feature_flags
            from src.backend.core.resilience.rpa_policy import (
                RPACallExhausted,
                get_rpa_policy,
            )

            policy = (
                get_rpa_policy()
                if feature_flags.webhook_resilience_policy_enabled
                else None
            )
            if policy is not None:
                response = await policy.call(
                    _do_post,
                    transport="webhook",
                    payload={"event": self.event, "url": self.url},
                )
            else:
                response = await _do_post()
        except Exception as exc:  # noqa: BLE001
            # RPACallExhausted уже отправил DLQ; legacy path — просто SinkResult.
            err_name = type(exc).__name__
            return SinkResult(
                ok=False,
                details={
                    "error": str(exc) or err_name,
                    "error_class": err_name,
                    "exhausted": isinstance(exc, RPACallExhausted)
                    if "RPACallExhausted" in dir()
                    else False,
                },
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

            from src.backend.core.net import OutboundHttpClient
        except ImportError:
            return False
        try:
            async with OutboundHttpClient(
                timeout=httpx.Timeout(self.timeout)
            ) as client:
                response = await client.request("HEAD", self.url)
        except Exception as _:  # noqa: BLE001
            return False
        return response.status_code < 500
