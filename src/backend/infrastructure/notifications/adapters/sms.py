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

Scaffolding-реализация: URL и payload-форматы помечены `# TODO: verify` —
заказчик подтверждает при интеграции.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Final, Literal

from src.infrastructure.notifications.adapters.base import NotificationChannel

_logger = logging.getLogger(__name__)

SMSProvider = Literal["mts", "megafon", "smsru"]


PROVIDER_ENDPOINTS: Final[dict[str, str]] = {
    "mts": "https://api.mts.ru/sms/v1/send",  # TODO: verify, может быть другой endpoint
    "megafon": "https://a2p-api.megafon.ru/sms/send",  # TODO: verify
    "smsru": "https://sms.ru/sms/send",  # проверено, стандартный endpoint SMS.ru
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

        from src.infrastructure.clients.transport.http_upstream import upstream

        client = upstream(self._upstream_name)

        # Per-provider payload. Сейчас только smsru полностью документирован;
        # mts/megafon — scaffolding (TODO: подтвердить интеграцию).
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

        # TODO: подтвердить endpoint и формат МТС при интеграции.
        if self._provider == "mts":
            headers = {"Authorization": f"Bearer {creds}"}
            payload = {
                "messages": [{"to": recipient, "from": self._sender_id, "text": body}]
            }
            response = await client.request(
                "POST", PROVIDER_ENDPOINTS["mts"], json=payload, headers=headers
            )
            if response.status_code >= 400:
                raise RuntimeError(f"MTS send failed: {response.status_code}")
            return

        # TODO: подтвердить endpoint и формат МегаФон.
        if self._provider == "megafon":
            headers = {"Authorization": creds}
            payload = {
                "destination": recipient,
                "sender": self._sender_id,
                "text": body,
            }
            response = await client.request(
                "POST", PROVIDER_ENDPOINTS["megafon"], json=payload, headers=headers
            )
            if response.status_code >= 400:
                raise RuntimeError(f"MegaFon send failed: {response.status_code}")
            return

        raise AssertionError(f"Unreachable: provider={self._provider}")

    async def health(self) -> bool:
        try:
            creds = self._credentials_provider()
            return bool(creds)
        except Exception:  # noqa: BLE001
            return False


assert isinstance(SMSAdapter(credentials_provider=lambda: ""), NotificationChannel)  # noqa: S101  # Protocol-conformance check на import


__all__ = ("SMSAdapter", "SMSProvider")
