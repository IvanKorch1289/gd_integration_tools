"""SMS adapter (IL2.2) — scaffolding для МТС / МегаФон / SMS.ru.

Все три провайдера используют HTTP REST-подход, поэтому единый adapter c
provider-селектором — правильная модель. Конкретные payload-форматы
зависят от провайдера и подключаются через PROVIDER_HANDLERS ниже.

Использование:

    adapter = SMSAdapter(
        provider="smsru",
        credentials_provider=lambda: settings.sms.api_id,
        upstream_name="sms-smsru",
    )
    gateway.register_channel(adapter)

Fallback chain провайдеров — deferred (по AskUserQuestion 2026-04-21).
Сейчас один provider per adapter; нужен второй — зарегистрировать второй
adapter с другим `kind` (например, "sms_backup").

Scaffolding-реализация: URL и payload-форматы требуют верификации при интеграции
с конкретным SMS-провайдером.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final, Literal

from src.backend.core.config.settings import settings
from src.backend.core.logging import get_logger
from src.backend.infrastructure.notifications.adapters.base import NotificationChannel
from src.backend.infrastructure.clients.base_connector import HealthResult

_logger = get_logger(__name__)

SMSProvider = Literal["mts", "megafon", "smsru"]


PROVIDER_ENDPOINTS: Final[dict[str, str]] = {
    "mts": settings.sms.mts_url,
    "megafon": settings.sms.megafon_url,
    "smsru": settings.sms.smsru_url,
}


class SMSAdapter:
    """Единый SMS-adapter для ru-провайдеров."""

    kind = "sms"

    def __init__(
        self,
        *,
        provider: SMSProvider = "smsru",
        credentials_provider: Callable[[], str],
        upstream_name: str = "sms-provider",
        sender_id: str = "GDI",  # имя отправителя (alpha-name)
    ) -> None:
        if provider not in PROVIDER_ENDPOINTS:
            raise ValueError(
                f"Unknown SMS provider '{provider}'. "
                f"Available: {', '.join(PROVIDER_ENDPOINTS)}"
            )
        self._provider = provider
        self._credentials_provider = credentials_provider
        self._upstream_name = upstream_name
        self._sender_id = sender_id

    async def send(
        self, *, recipient: str, subject: str, body: str, metadata: dict[str, Any]
    ) -> None:
        """Отправить SMS.

        SMS не поддерживает subject — используется только body. Обычно
        subject встраивается в начало body сервисом, если нужно.

        `recipient` — номер в E.164-формате (+79998887766).
        """
        creds = self._credentials_provider()
        if not creds:
            raise RuntimeError(f"SMS credentials missing for provider={self._provider}")

        from src.backend.infrastructure.clients.transport.http_upstream import upstream

        client = upstream(self._upstream_name)

        # Per-provider payload. Сейчас только smsru полностью документирован;
        # mts/megafon — scaffolding (TODO(S40-W6): подтвердить интеграцию).
        if self._provider == "smsru":
            params = {
                "api_id": creds,
                "to": recipient.lstrip("+"),
                "msg": body,
                "json": "1",
                "from": self._sender_id,
            }
            response = await client.request(
                "POST", PROVIDER_ENDPOINTS["smsru"], params=params
            )
            if response.status_code >= 400:
                raise RuntimeError(f"SMS.ru send failed: {response.status_code}")
            data = response.json()
            if data.get("status") != "OK":
                raise RuntimeError(f"SMS.ru API error: {data}")
            return

        # S216: реализация для MTS и Megafon через generic httpx POST.
        # Endpoint URL берётся из SMSSettings (см. core/config/services/sms.py),
        # payload — JSON {"to", "message", "from"}. Provider-specific схемы
        # могут отличаться (Bearer token, X-API-Key header и т.п.); этот scaffold
        # передаёт credentials через query param ``api_id`` (как smsru). При
        # несовпадении реального contract — добавить provider-specific handler.
        if self._provider in ("mts", "megafon"):
            params = {
                "api_id": creds,
                "to": recipient.lstrip("+"),
                "msg": body,
                "from": self._sender_id,
            }
            response = await client.request(
                "POST", PROVIDER_ENDPOINTS[self._provider], params=params
            )
            if response.status_code >= 400:
                raise RuntimeError(
                    f"{self._provider} SMS send failed: HTTP {response.status_code}: "
                    f"{response.text[:200]}"
                )
            # Best-effort: парсим JSON-ответ, проверяем status/success поле.
            try:
                data = response.json()
            except Exception:
                _logger.warning(
                    "SMS/%s: non-JSON response (status=%d)",
                    self._provider,
                    response.status_code,
                )
                return
            if isinstance(data, dict) and data.get("status") not in (None, "OK", "ok", "success", 200, "200"):
                raise RuntimeError(
                    f"{self._provider} SMS API error: {data}"
                )
            return

        raise AssertionError(f"Unreachable: provider={self._provider}")

    async def health(self, mode: str = "fast") -> HealthResult:
        import time

        start = time.perf_counter()
        try:
            creds = self._credentials_provider()
            if not creds:
                latency_ms = (time.perf_counter() - start) * 1000.0
                return HealthResult.failed(
                    error="SMS credentials missing",
                    mode=mode,
                    latency_ms=latency_ms,
                )
            latency_ms = (time.perf_counter() - start) * 1000.0
            return HealthResult.ok(latency_ms=latency_ms, mode=mode)
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000.0
            return HealthResult.failed(
                error=f"{type(exc).__name__}: {exc}", mode=mode, latency_ms=latency_ms
            )


assert isinstance(
    SMSAdapter(credentials_provider=lambda: ""), NotificationChannel
)  # Protocol-conformance check на import


__all__ = ("SMSAdapter", "SMSProvider")
