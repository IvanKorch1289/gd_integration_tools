"""Channel adapters для NotificationGateway.

Каждый adapter реализует `NotificationChannel` Protocol (см. `base.py`):

  * ``kind`` — string identifier канала ("email", "sms", ...).
  * ``async send(recipient, subject, body, metadata)`` — отправка.
  * ``async health() -> bool`` — liveness-probe.

Адаптеры инжектируются в NotificationGateway через `register_channel()`.

Текущий набор (IL2.2):
  * email — via существующий SMTP-pool (aiosmtplib, IL1).
  * telegram — Telegram Bot API через httpx.
  * webhook — generic POST с HMAC signature + SSRF guard.
  * sms — МТС / МегаФон / SMS.ru через httpx (scaffolding).
  * slack — webhook + API (scaffolding).
  * teams — webhook (scaffolding).
  * express — eXpress BotX (re-export из legacy).

Scaffolding-адаптеры — placeholder'ы с правильным интерфейсом; конкретная
интеграция подключается per-customer в deployment-конфиге.
"""

from app.infrastructure.notifications.adapters.base import NotificationChannel

__all__ = ("NotificationChannel",)
