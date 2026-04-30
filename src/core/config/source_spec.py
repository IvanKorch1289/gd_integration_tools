"""W23 — pydantic-модели описания Source в YAML.

YAML-spec (``config_profiles/sources.yml`` или секция ``sources:``
в основном профиле):

```yaml
sources:
  - id: orders_webhook
    kind: webhook
    action: orders.process_payment
    mode: sync          # InvocationMode (default: sync)
    idempotency: true   # включить dedup по event_id
    reply_channel: null
    config:             # backend-специфика
      path: /webhooks/orders/payment
      hmac_header: X-Signature
      hmac_secret: ${WEBHOOK_ORDERS_SECRET}
      timestamp_header: X-Timestamp
      timestamp_window_seconds: 300
```

``config`` — свободный dict, валидируется конкретным backend-классом
(``WebhookSource``, ``MQSource``, ...). Это даёт расширяемость без
изменения схемы при добавлении нового kind.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.core.interfaces.invoker import InvocationMode
from src.core.interfaces.source import SourceKind

__all__ = ("SourceSpec", "SourcesSpecFile")


class SourceSpec(BaseModel):
    """Описание одного Source-инстанса.

    Поля:

    * ``id`` — уникальный source_id (используется в SourceRegistry).
    * ``kind`` — :class:`SourceKind` (``webhook`` / ``mq`` / ...).
    * ``action`` — имя action, в который Invoker направит событие.
    * ``mode`` — режим Invoker (default ``sync``).
    * ``reply_channel`` — для асинхронных режимов.
    * ``idempotency`` — включить ли dedup по ``event_id`` (default ``True``).
    * ``config`` — backend-специфичные параметры.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, description="Уникальный source_id.")
    kind: SourceKind = Field(..., description="Тип источника.")
    action: str = Field(
        ...,
        min_length=1,
        description="Имя action, на который маршрутизируется событие.",
    )
    mode: InvocationMode = Field(
        default=InvocationMode.SYNC,
        description="Режим Invoker (sync/async-api/async-queue/...).",
    )
    reply_channel: str | None = Field(
        default=None, description="Канал ответа (для асинхронных режимов). null = нет."
    )
    idempotency: bool = Field(
        default=True, description="Включить dedup по event_id перед вызовом Invoker."
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Backend-специфичные параметры; валидируется backend-классом.",
    )


class SourcesSpecFile(BaseModel):
    """Корневой контейнер YAML-spec файла источников."""

    model_config = ConfigDict(extra="forbid")

    sources: list[SourceSpec] = Field(default_factory=list)
