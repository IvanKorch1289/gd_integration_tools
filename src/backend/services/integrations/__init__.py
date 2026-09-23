"""Сервисный слой интеграций.

W24 добавил :mod:`import_service` — orchestration над ImportGateway.
pre-W26 добавил :mod:`imported_action_service` — каталог + единая точка
диспатча импортированных endpoint'ов.
S203 W4 добавил :mod:`facade` — единый ``IntegrationFacade`` с capability
gating для extensions/agent'ов.
"""

from src.backend.services.integrations.facade import (
    IntegrationFacade,
    get_integration_facade,
)
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
    "IntegrationFacade",
    "get_import_service",
    "get_imported_action_service",
    "get_integration_facade",
)
