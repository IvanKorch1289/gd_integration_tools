"""Public prelude для extension-разработчиков gd_integration_tools.

V11 plugin layout: extensions/<name>/{plugin.py, plugin.toml, services/, repositories/}.

Этот файл — canonical точка входа для common imports при разработке
extension'а. Вместо:

    from src.backend.core.interfaces.plugin import BasePlugin
    from src.backend.core.services.base_service import BaseService
    # SQLAlchemyRepository loaded lazily via __getattr__ (ponytail D111)
    from src.backend.core.errors import ServiceError, NotFoundError
    from src.backend.core.database.session import main_session_manager
    from src.backend.core.domain.models.base import BaseModel

можно писать:

    from extensions import (
        BasePlugin, ActionRegistryProtocol, PluginContext,
        BaseService, SQLAlchemyRepository,
        ServiceError, NotFoundError,
        main_session_manager, BaseModel,
    )

Канонические импорты — из core/ (per tools/check_layers.py
ALLOWED["extensions"]={"core"}).  Канонический plugin.py.j2 template
должен быть обновлён чтобы использовать этот prelude (см. P1 план).

Импортировано по статистике (S168 W9): 10× BasePlugin, 5× load_plugin_manifest,
4× BaseService, 4× SQLAlchemyRepository, 3× ServiceError/NotFoundError,
3× main_session_manager.

Out of scope: Pydantic schemas (route_schemas/*) — extension-specific,
не добавляем в prelude (предотвращает circular import).
"""

# Plugin lifecycle (canonical from core.interfaces.plugin)
from src.backend.core.interfaces.plugin import (
    ActionRegistryProtocol,
    BasePlugin,
    PluginContext,
    PluginInfo,
    ProcessorRegistryProtocol,
    RepositoryRegistryProtocol,
)

# Service base (canonical from core.services.base_service)
from src.backend.core.services.base_service import BaseService

# Repository base (canonical from core.repositories.base)
# Common errors (canonical from core.errors)
from src.backend.core.errors import (
    NotFoundError,
    ServiceError,
)

# Session manager (canonical from core.database.session)
from src.backend.core.database.session import main_session_manager

# Base ORM model (canonical from core.domain.models.base)
from src.backend.core.domain.models.base import BaseModel

# Repository Protocols (canonical from core.interfaces.repositories)
from src.backend.core.interfaces.repositories import (
    FileRepositoryProtocol,
    OrderKindRepositoryProtocol,
    OrderRepositoryProtocol,
    UserRepositoryProtocol,
)


__all__ = [
    # Plugin lifecycle
    "ActionRegistryProtocol",
    "BasePlugin",
    "PluginContext",
    "PluginInfo",
    "ProcessorRegistryProtocol",
    "RepositoryRegistryProtocol",
    # Service / Repository
    "BaseService",
    "SQLAlchemyRepository",
    "BaseModel",
    # Errors
    "NotFoundError",
    "ServiceError",
    # Session
    "main_session_manager",
    # Protocols
    "FileRepositoryProtocol",
    "OrderKindRepositoryProtocol",
    "OrderRepositoryProtocol",
    "UserRepositoryProtocol",
]


def __getattr__(name: str) -> Any:
    """PEP 562 lazy attribute access (Sprint 36 — ponytail D111)."""
    if name == "SQLAlchemyRepository":
        from src.backend.core.repositories.base import SQLAlchemyRepository
        return SQLAlchemyRepository
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
