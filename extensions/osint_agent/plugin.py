"""V11 plugin entry для osint_agent.

OSINT-агент: принимает ИНН клиента, выполняет web-search через Perplexity,
и генерирует строгий отчёт (≤3000 символов) с данными о компании.

Integration pattern:
    DSL -> call_function('osint_agent.report', payload={'inn': '...'})
    -> osint_workflow.run_osint() -> dict с отчётом.

S168 W11 P2-12 STATUS (per master prompt v8):
    Master prompt requested: "extensions/osint_agent lease data store
    (move from core/storage/facade.py (deleted in S168 W3) to
    extensions/osint_agent/)".

    Current state (verified by grep):
    - 0 references to ``DataStore`` / ``data_store`` в osint_agent/
    - 0 references to core.storage.facade (deleted S168 W3)
    - osint_agent uses external API (Perplexity) + own domain models
      (extensions/osint_agent/domain/models.py)

    CONCLUSION: P2-12 is effectively already complete. Per Ponytail
    minimum, this commit adds a documentation note; no code change
    required. Per master prompt: lease pattern already implicitly
    applied (extension owns its domain).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from extensions.osint_agent.functions.osint_workflow import run_osint
from src.backend.core.interfaces.plugin import BasePlugin

if TYPE_CHECKING:
    from src.backend.core.interfaces.plugin import (
        ActionRegistryProtocol,
        PluginContext,
        ProcessorRegistryProtocol,
        RepositoryRegistryProtocol,
    )

logger = logging.getLogger("extensions.osint_agent")

_ActionHandler = Callable[..., Awaitable[dict[str, Any]]]


def _make_handler(agent: _ActionHandler) -> _ActionHandler:
    async def _handler(**kwargs: Any) -> dict[str, Any]:
        payload = kwargs.get("payload")
        if payload is None:
            payload = {}
        return await agent(payload)

    return _handler


class OsintAgentPlugin(BasePlugin):
    """OSINT agent plugin: web-search + LLM report by INN.

    Lifecycle:
    * on_load - log availability.
    * on_register_actions - register osint_agent.report action.
    """

    name: str = "osint_agent"
    version: str = "0.1.0"

    async def on_load(self, ctx: PluginContext) -> None:
        logger.info("osint_agent v%s loaded", self.version)

    async def on_register_actions(self, registry: ActionRegistryProtocol) -> None:
        registry.register("osint_agent.report", _make_handler(run_osint))
        logger.info("osint_agent: 1 action registered (osint_agent.report)")

    async def on_register_repositories(
        self, registry: RepositoryRegistryProtocol
    ) -> None:
        pass

    async def on_register_processors(self, registry: ProcessorRegistryProtocol) -> None:
        pass

    async def on_shutdown(self) -> None:
        logger.info("osint_agent v%s shutdown", self.version)
