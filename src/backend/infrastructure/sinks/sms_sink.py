"""SmsSink — отправка SMS через российских провайдеров (S203 W5).

Реализует :class:`Sink` для ``SinkKind.SMS``. Поддерживает провайдеров
``smsru``, ``mts``, ``megafon`` через единый API на базе ``httpx``.

API::

    sink = SmsSink(
        sink_id="alerts.sms",
        provider="smsru",
        api_id="...",
        from_name="MyBank",
        default_to="+79991234567",
    )
    result = await sink.send({"to": "+79991234567", "body": "Hello"})

``send(payload)`` принимает dict: ``{"to": "+7...", "body": "...",
"from": "SenderName"}`` или строку — отправляется на ``default_to``.

Закрывает gap IL2.2 (SMSSettings уже определён в
``core/config/services/sms.py``). Health через HEAD на endpoint провайдера.

Ponytail: один класс, без абстракций. Если появится второй провайдер
с сильно отличающимся API — выделить SmsProvider Protocol, не раньше.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, ClassVar

from src.backend.core.config.services.sms import sms_settings
from src.backend.core.interfaces.sink import Sink, SinkKind, SinkResult
from src.backend.core.resilience.connector_breaker import with_breaker
from src.backend.core.resilience.retry import with_retry
from src.backend.core.security.connector_auth import require_capability
from src.backend.infrastructure.clients.base_connector import HealthResult
from src.backend.infrastructure.security.connector_rate_limiter import (
    get_connector_rate_limiter,
)
from src.backend.infrastructure.sinks._timeouts import (
    DEFAULT_SINK_TIMEOUT_S,  # noqa: F401 — re-exported for sink factory
)

__all__ = ("SmsSink",)


@dataclass(slots=True)
class SmsSink(Sink):
    """HTTP-based SMS sink для российских провайдеров.

    Args:
        sink_id: Уникальный идентификатор.
        provider: Один из ``"smsru"``, ``"mts"``, ``"megafon"``.
        api_id: API-ключ провайдера (передаётся как query-param или header).
        from_name: Имя отправителя (регистрируется в личном кабинете).
        default_to: Номер по умолчанию (E.164, например ``"+79991234567"``).
        timeout_s: HTTP timeout (default 10).
    """

    # Валидные провайдеры — class-level чтобы enum-style без жёсткого import.
    PROVIDERS: ClassVar[tuple[str, ...]] = ("smsru", "mts", "megafon")

    sink_id: str
    provider: str = "smsru"
    api_id: str = ""
    from_name: str = ""
    default_to: str | None = None
    timeout_s: float = 10.0
    kind: SinkKind = field(default=SinkKind.SMS, init=False)

    def __post_init__(self) -> None:
        if self.provider not in self.PROVIDERS:
            raise ValueError(
                f"sms_sink: provider must be one of {self.PROVIDERS}, got {self.provider!r}"
            )

    def _endpoint(self) -> str:
        """URL провайдера из SMSSettings."""
        return {
            "smsru": sms_settings.smsru_url,
            "mts": sms_settings.mts_url,
            "megafon": sms_settings.megafon_url,
        }[self.provider]

    @with_breaker("sms_sink")
    @with_retry(max_attempts=3, initial_backoff=2.0,
        retry_on=(ConnectionError, TimeoutError, OSError))
    @require_capability("sms.send", action="write")
    async def send(self, payload: Any) -> SinkResult:
        """S203 W5: отправить SMS через httpx POST.

        Поддерживает payload dict ``{"to": ..., "body": ..., "from": ...}``
        либо строку (→ отправляется на ``default_to``).
        """
        # Per-connector rate limit (5/s — большинство SMS API ограничены).
        limiter = get_connector_rate_limiter()
        limiter.register(f"{self.sink_id}_{self.kind}", "5/s", 5)
        await limiter.check(f"{self.sink_id}_{self.kind}")

        to, body, sender = self._extract_payload(payload)
        if not to or not body:
            return SinkResult(ok=False, details={"error": "missing to/body"})

        try:
            import httpx

            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                resp = await client.post(
                    self._endpoint(),
                    params={
                        "api_id": self.api_id,
                        "to": to,
                        "msg": body,
                        "from": sender or self.from_name,
                        "json": 1,
                    },
                )
                ok = 200 <= resp.status_code < 300
                details: dict[str, Any] = {
                    "status_code": resp.status_code,
                    "provider": self.provider,
                }
                # sms.ru возвращает JSON {"status": "OK", "sms_id": "..."}.
                try:
                    payload_resp: Any = resp.json()
                    if isinstance(payload_resp, dict):
                        sms_id = payload_resp.get("sms_id")
                        if sms_id is not None:
                            details["external_id"] = str(sms_id)
                except Exception:
                    pass
                return SinkResult(ok=ok, details=details)
        except Exception as exc:
            return SinkResult(
                ok=False, details={"error": str(exc) or exc.__class__.__name__}
            )

    def _extract_payload(self, payload: Any) -> tuple[str | None, str | None, str | None]:
        """Нормализация payload → (to, body, from)."""
        if isinstance(payload, dict):
            return (
                payload.get("to") or self.default_to,
                payload.get("body"),
                payload.get("from"),
            )
        if isinstance(payload, str):
            return self.default_to, payload, None
        return None, None, None

    async def health(self, mode: str = "fast") -> HealthResult:
        """HEAD на endpoint провайдера (cheap probe)."""
        try:
            import httpx

            start = time.perf_counter()
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.head(self._endpoint())
                latency_ms = (time.perf_counter() - start) * 1000.0
                if 200 <= resp.status_code < 500:
                    return HealthResult.ok(
                        latency_ms=latency_ms,
                        mode=mode,
                        provider=self.provider,
                        status_code=resp.status_code,
                    )
                return HealthResult.failed(
                    error=f"provider returned HTTP {resp.status_code}",
                    mode=mode,
                    latency_ms=latency_ms,
                )
        except Exception as exc:
            return HealthResult.failed(
                error=f"{type(exc).__name__}: {exc}", mode=mode
            )
