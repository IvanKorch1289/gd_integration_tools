"""W23 — :class:`HttpSource` (тонкий вариант webhook без HMAC).

Используется для inbound HTTP-эндпоинтов без подписи (внутренние сервисы,
trusted-сети). Семантика идентична :class:`WebhookSource`, но без
обязательной HMAC-проверки. Если нужен HMAC — берите ``WebhookSource``.
"""

from __future__ import annotations

from src.infrastructure.sources.webhook import WebhookSource

__all__ = ("HttpSource",)


class HttpSource(WebhookSource):
    """HTTP-source без обязательной HMAC-проверки.

    Все аргументы наследуются от :class:`WebhookSource`; ``hmac_secret``
    по умолчанию ``None``, проверка подписи отключена.
    """
