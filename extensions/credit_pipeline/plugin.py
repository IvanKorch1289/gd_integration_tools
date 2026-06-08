"""V11 plugin entry для credit_pipeline (S76 W2 — real actions).

Плагин кредитного конвейера (real impl, S76 W1 + W2). Регистрирует 3
actions для интеграции scoring/document_parser/decision агентов в
основной DSL через ``on_register_actions`` hook.

Связанные ADR:

* ADR-042 — формат ``plugin.toml`` (V11);
* ADR-044 — capability vocabulary;
* ADR-0099 — v28 reconciliation (S76 W1 closeout context).

Wave: ``[wave:s76/w2-plugin-action-registration]``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from extensions.credit_pipeline.agents import (
    decision_agent,
    document_parser_agent,
    scoring_agent,
)
from src.backend.core.interfaces.plugin import BasePlugin

if TYPE_CHECKING:
    from src.backend.core.interfaces.plugin import (
        ActionRegistryProtocol,
        PluginContext,
        ProcessorRegistryProtocol,
        RepositoryRegistryProtocol,
    )

logger = logging.getLogger("extensions.credit_pipeline")

# Async wrapper signature: action handler принимает произвольные kwargs
# (DSL engine может передавать tenant_id, correlation_id и т.д.) и
# возвращает dict. Payload извлекается по ключу "payload".
_ActionHandler = Callable[..., Awaitable[dict[str, Any]]]


def _make_handler(agent: _ActionHandler) -> _ActionHandler:
    """Создаёт обёртку над agent для регистрации как action.

    Извлекает ``payload`` из kwargs (default — пустой dict) и вызывает
    agent. Единый шаблон для всех actions кредитного pipeline.
    Используется в ``on_register_actions`` для устранения copy-paste.
    """

    async def _handler(**kwargs: Any) -> dict[str, Any]:
        payload = kwargs.get("payload")
        if payload is None:
            payload = {}
        return await agent(payload)

    return _handler


class CreditPipelinePlugin(BasePlugin):
    """Плагин кредитного конвейера (S76 — real agents wired).

    Lifecycle:
    * ``on_load`` — логирует plugin version, наличие 3 real agents.
    * ``on_register_actions`` — регистрирует ``credit_pipeline.{score,
      parse, decide}`` через ``_make_handler`` factory.
    * ``on_register_repositories`` — defer (DB repos ещё не реализованы).
    * ``on_register_processors`` — defer (DSL processors ещё не нужны;
      actions достаточно для текущего use case).
    * ``on_shutdown`` — graceful log.

    Integration:
    * DSL → ``call_function('credit_pipeline.score', payload)``
      → scoring_agent → score dict.
    * DSL chain → ``call_function('credit_pipeline.decide', {
      'applicant_id': ..., 'scoring_agent': scoring_output })``
      → decision_agent → decision dict.

    Real impl lives в ``extensions/credit_pipeline/agents/`` (S76 W1).
    """

    name: str = "credit_pipeline"
    version: str = "0.1.0"

    async def on_load(self, ctx: PluginContext) -> None:
        """Сохраняет ``PluginContext`` и логирует доступность agents."""
        logger.info(
            "credit_pipeline v%s loaded (3 real agents: %s, %s, %s)",
            self.version,
            scoring_agent.__name__,
            document_parser_agent.__name__,
            decision_agent.__name__,
        )

    async def on_register_actions(self, registry: ActionRegistryProtocol) -> None:
        """Регистрирует 3 actions, оборачивающих real agents.

        Action IDs:
        * ``credit_pipeline.score`` — scoring_agent.
        * ``credit_pipeline.parse`` — document_parser_agent.
        * ``credit_pipeline.decide`` — decision_agent.

        Каждый handler создаётся через ``_make_handler`` factory
        (единый шаблон: извлечение payload из kwargs → вызов agent).
        """

        registry.register("credit_pipeline.score", _make_handler(scoring_agent))
        registry.register("credit_pipeline.parse", _make_handler(document_parser_agent))
        registry.register("credit_pipeline.decide", _make_handler(decision_agent))

        logger.info(
            "credit_pipeline: 3 actions registered "
            "(credit_pipeline.{score,parse,decide})"
        )

    async def on_register_repositories(
        self, registry: RepositoryRegistryProtocol
    ) -> None:
        """Defer: DB repository hooks для credit_applications / reports.

        Capabilities ``db.read/write credit_applications`` уже
        задекларированы в plugin.toml — сразу готовы к W3+.
        """

    async def on_register_processors(self, registry: ProcessorRegistryProtocol) -> None:
        """Defer: DSL processors не требуются (actions достаточно)."""

    async def on_shutdown(self) -> None:
        """Логирует факт выключения плагина."""
        logger.info("credit_pipeline v%s shutdown", self.version)
