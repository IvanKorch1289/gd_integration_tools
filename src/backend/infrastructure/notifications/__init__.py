"""Infrastructure notifications — единый gate для уведомлений.

IL2.2 (ADR-023). Публичный API:

    from src.backend.infrastructure.notifications import (  # noqa: F401 — re-export
        NotificationGateway,
        TemplateRegistry,
        get_gateway,
    )

    gateway = get_gateway()
    await gateway.send_tx(
        channel="email",
        template_key="kyc_approved",
        locale="ru",
        context={"name": "Иван"},
        recipient="ivan@example.com",
    )
"""

from src.backend.infrastructure.notifications.gateway import (  # noqa: F401 — re-export
    NotificationGateway,
    SendResult,
    get_gateway,
)
from src.backend.infrastructure.notifications.priority import Priority, PriorityRouter
from src.backend.infrastructure.notifications.templates import (  # noqa: F401 — re-export
    TemplateRegistry,
    get_template_registry,
)

__all__ = (
    "NotificationGateway",
    "Priority",
    "PriorityRouter",
    "SendResult",
    "TemplateRegistry",
    "get_gateway",
    "get_template_registry",
)
