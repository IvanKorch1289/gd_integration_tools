"""DI-примитивы для DSL (Sprint 40).

Публичный API::

    from src.backend.dsl.di import Container, inject

    @inject
    async def handler(
        exchange: Exchange[Any],
        context: ExecutionContext,
        db: DatabaseSessionManager = Container.depends(),
    ) -> None:
        ...
"""

from src.backend.dsl.di.container import Container, DIError
from src.backend.dsl.di.decorators import inject
from src.backend.dsl.di.types import InjectMarker

__all__ = ("Container", "DIError", "InjectMarker", "inject")
