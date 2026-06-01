"""Сервисный слой интеграций.

W24 добавил :mod:`import_service` — orchestration над ImportGateway.
pre-W26 добавил :mod:`imported_action_service` — каталог + единая точка
диспатча импортированных endpoint'ов.
"""

from src.backend.services.integrations.import_service import (
    ImportService,
    get_import_service,
)
from src.backend.services.integrations.imported_action_service import (
    EndpointMeta,
    ImportedActionService,
    get_imported_action_service,
)

__all__ = (
    "EndpointMeta",
    "ImportService",
    "ImportedActionService",
    "get_import_service",
    "get_imported_action_service",
)
