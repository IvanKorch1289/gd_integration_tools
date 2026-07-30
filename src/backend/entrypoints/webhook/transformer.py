"""Webhook Transformer — backward-compat shim (Layer 11 Cycle 3).

Per architecture invariants: services не должны зависеть от entrypoints.
Класс WebhookRelay перенесён в :mod:`src.backend.services.integrations.webhook_relay`.

Этот shim оставлен для backward-compat с extensions/test, которые
импортируют напрямую из старого location. Новый код должен импортировать
из :mod:`src.backend.services.integrations.webhook_relay`.
"""

from __future__ import annotations

from src.backend.services.integrations.webhook_relay import (  # noqa: F401
    DLQEntry,
    RelayRule,
    WebhookRelay,
    get_webhook_relay,
)

__all__ = ("DLQEntry", "RelayRule", "WebhookRelay", "get_webhook_relay")
