"""Composition root проекта (Wave 6).

Здесь собирается граф зависимостей: FastAPI app, lifecycle, DI-биндинги,
регистрация сервисов и инфраструктурный bootstrap. Модули в этом пакете
лежат в plugins/-слое, поскольку им разрешено импортировать все слои
(entrypoints, services, infrastructure, schemas, core).
"""

from src.backend.plugins.composition.app_factory import (
    create_app,  # noqa: F401 — re-export
)
from src.backend.plugins.composition.lifecycle import lifespan  # noqa: F401 — re-export
from src.backend.plugins.composition.setup_infra import (  # noqa: F401 — re-export
    ending,
    starting,
)

__all__ = ("create_app", "ending", "lifespan", "starting")
