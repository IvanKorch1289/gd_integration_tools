"""V11 plugin entry для credit_pipeline (Sprint 7 Team T2 scaffold).

Это пустой stub-плагин; Team T3 (Sprint 8+) наполнит lifecycle-хуки
конкретной логикой кредитного конвейера. См. README.md в каталоге плагина
для дорожной карты.

Связанные ADR:

* ADR-042 — формат ``plugin.toml`` (V11);
* ADR-044 — capability vocabulary.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.backend.core.interfaces.plugin import BasePlugin

if TYPE_CHECKING:
    from src.backend.core.interfaces.plugin import (
        ActionRegistryProtocol,
        PluginContext,
        ProcessorRegistryProtocol,
        RepositoryRegistryProtocol,
    )

__all__ = ("CreditPipelinePlugin",)

logger = logging.getLogger("extensions.credit_pipeline")


class CreditPipelinePlugin(BasePlugin):
    """Scaffold-плагин кредитного конвейера.

    На текущий момент (Sprint 7 Team T2) — заглушка без бизнес-логики.
    Team T3 (Sprint 8+) подключит:

    * actions: ``credit.score.calculate``, ``credit.application.create``;
    * repositories: ``credit_applications``, ``credit_reports``;
    * processors: вспомогательные DSL-шаги для конвейера;
    * workflows: ``credit_assessment.workflow.yaml``;
    * routes: декларативные маршруты в ``routes/<name>/``.
    """

    name = "credit_pipeline"
    version = "0.0.1"

    async def on_load(self, ctx: PluginContext) -> None:
        """Сохраняет ``PluginContext`` для будущей реализации (T3)."""
        self._ctx = ctx
        logger.info("credit_pipeline scaffold loaded")

    async def on_register_actions(self, registry: ActionRegistryProtocol) -> None:
        """TODO Team T3: зарегистрировать actions кредитного конвейера."""

    async def on_register_repositories(
        self, registry: RepositoryRegistryProtocol
    ) -> None:
        """TODO Team T3: подключить repository-hooks credit_applications/reports."""

    async def on_register_processors(
        self, registry: ProcessorRegistryProtocol
    ) -> None:
        """TODO Team T3: кастомные DSL-процессоры конвейера."""

    async def on_shutdown(self) -> None:
        """Логирует факт выключения scaffold-плагина."""
        logger.info("credit_pipeline scaffold shutdown")
