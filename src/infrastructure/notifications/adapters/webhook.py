"""Generic HTTP webhook adapter (IL2.2).

Использует httpx-upstream профили (IL2.6) для per-endpoint pool/RL/CB.
HMAC-подпись (SHA-256) передаётся в заголовке `X-Signature`. SSRF
защита: only http/https, блокирует localhost / 127.0.0.1 / 10.* / 192.168.*
/ 172.16-31.* без явного opt-in `allow_internal=True` в metadata.

Использование:

    adapter = WebhookAdapter(
        upstream_name="my-webhook",  # должен быть зарегистрирован в UpstreamRegistry
        secret_provider=lambda: settings.webhook_secret,
    )
    gateway.register_channel(adapter)
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
from typing import Any, Callable
from urllib.parse import urlparse

from src.infrastructure.notifications.adapters.base import NotificationChannel

_logger = logging.getLogger(__name__)


class WebhookAdapter:
    """Webhook channel adapter."""

    kind = "webhook"

    def __init__(
        self,
        *,
        upstream_name: str = "webhook-default",
        secret_provider: Callable[[], str] | None = None,
        signature_header: str = "X-Signature",
    ) -> None:
        self._upstream_name = upstream_name
        self._secret_provider = secret_provider
        self._signature_header = signature_header

    async def send(
        self, *, recipient: str, subject: str, body: str, metadata: dict[str, Any]
    ) -> None:
        """Отправить POST на `recipient` (URL).

        `subject` попадает в заголовок `X-Subject`, `body` — как JSON payload.
        Если ``recipient`` нарушает SSRF-правила — `ValueError`.
        """
        if not _url_is_safe(recipient, metadata.get("allow_internal", False)):
            raise ValueError(f"SSRF-protected URL blocked: {recipient}")

        payload = {
            "subject": subject,
            "body": body,
            "request_id": metadata.get("request_id"),
            "priority": metadata.get("priority"),
        }
        headers = {"X-Subject": subject[:200]}

        if self._secret_provider:
            secret = self._secret_provider()
            body_bytes = _json_encode(payload)
            signature = hmac.new(
                secret.encode("utf-8"), body_bytes, hashlib.sha256
            ).hexdigest()
            headers[self._signature_header] = f"sha256={signature}"

        # Используем per-upstream httpx-клиент (IL2.6).
        from src.infrastructure.clients.transport.http_upstream import upstream

        client = upstream(self._upstream_name)
        response = await client.request(
            "POST", recipient, json=payload, headers=headers
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"webhook POST failed: {response.status_code} {response.text[:200]}"
            )

    async def health(self) -> bool:
        """Проверить, что upstream зарегистрирован."""
        try:
            from src.infrastructure.clients.transport.http_upstream import (
                upstream_registry,
            )

            upstream_registry.get(self._upstream_name)
            return True
        except Exception:  # noqa: BLE001
            return False


def _url_is_safe(url: str, allow_internal: bool) -> bool:
    """Простая SSRF-защита: запрет на internal IPs + non-HTTP схем.

    * Http/https only.
    * Host должен быть не loopback / private, если `allow_internal=False`.
    """
    try:
        parsed = urlparse(url)
    except Exception:  # noqa: BLE001
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname or ""
    if not host:
        return False
    if allow_internal:
        return True
    if host in ("localhost", "127.0.0.1", "::1"):
        return False
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return False
    except ValueError:
        # Не IP — это доменное имя. Оставляем, но предупреждаем в логах
        # (подробный DNS-rebind-fix выходит за рамки IL2.2).
        pass
    return True


def _json_encode(payload: dict[str, Any]) -> bytes:
    try:
        import orjson

        return orjson.dumps(payload)
    except ImportError:
        import json

        return json.dumps(payload, ensure_ascii=False).encode("utf-8")


# Явный Protocol check (опционально).
assert isinstance(WebhookAdapter(), NotificationChannel)


__all__ = ("WebhookAdapter",)
