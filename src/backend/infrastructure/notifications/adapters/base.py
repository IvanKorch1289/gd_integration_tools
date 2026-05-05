"""Base Protocol для NotificationChannel adapters (IL2.2)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class NotificationChannel(Protocol):
    """Контракт, которому должен соответствовать каждый channel-адаптер.

    * ``kind`` — уникальный ключ канала ("email", "sms", ...).
    * ``send(recipient, subject, body, metadata)`` — отправка. Ошибки
      пробрасываются; gateway считает их retryable и поставит в retry-цикл
      (до `max_retries`), потом — в DLQ.
    * ``health()`` — простой boolean liveness. Gateway использует для
      включения канала в общий health-aggregate.
    """

    kind: str

    async def send(
        self, *, recipient: str, subject: str, body: str, metadata: dict[str, Any]
    ) -> None: ...

    async def health(self) -> bool: ...


__all__ = ("NotificationChannel",)
