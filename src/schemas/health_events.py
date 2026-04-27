"""События смены overall-статуса health-aggregator (Wave 6.4)."""


from typing import Any

from pydantic import BaseModel, Field

__all__ = ("HealthTransitionEvent",)


class HealthTransitionEvent(BaseModel):
    """Публикуется в ``events.health`` при смене overall-статуса.

    Подписчики могут отправлять алерты в Notification-каналы.
    """

    previous_status: str = Field(..., description="Предыдущий overall-статус")
    current_status: str = Field(..., description="Текущий overall-статус")
    components: dict[str, dict[str, Any]] = Field(
        default_factory=dict, description="Снимок компонентных проверок"
    )
