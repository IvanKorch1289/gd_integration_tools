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
from typing import TYPE_CHECKING, Any

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
    """Плагин кредитного конвейера (S76 — real agents wired).

    Lifecycle:
    * ``on_load`` — логирует plugin version, наличие 3 real agents.
    * ``on_register_actions`` — регистрирует ``credit_pipeline.{score,
      parse, decide}`` (обёртки над ``extensions.credit_pipeline.
      agents``).
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

    name = "credit_pipeline"
    version = "0.1.0"

    async def on_load(self, ctx: PluginContext) -> None:
        """Сохраняет ``PluginContext`` и логирует доступность agents."""
        self._ctx = ctx
        # Импорт внутри метода: lazy-load чтобы избежать циклических
        # импортов при plugin discovery (см. ADR-042 — discovery-first).
        from extensions.credit_pipeline.agents import (
            decision_agent,
            document_parser_agent,
            scoring_agent,
        )

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

        Каждый handler — async def(**kwargs) → dict. Принимает
        ``payload`` (dict) и ``**kwargs`` (для будущих расширений).
        """

        # Lazy import: см. on_load (discovery-first).
        from extensions.credit_pipeline.agents import (
            decision_agent,
            document_parser_agent,
            scoring_agent,
        )

        async def _score(**kwargs: Any) -> dict[str, Any]:
            """Wrapper для scoring_agent — кредитный скоринг."""
            payload = kwargs.get("payload") or {}
            return await scoring_agent(payload)

        async def _parse(**kwargs: Any) -> dict[str, Any]:
            """Wrapper для document_parser_agent — извлечение полей."""
            payload = kwargs.get("payload") or {}
            return await document_parser_agent(payload)

        async def _decide(**kwargs: Any) -> dict[str, Any]:
            """Wrapper для decision_agent — финальное решение."""
            payload = kwargs.get("payload") or {}
            return await decision_agent(payload)

        registry.register("credit_pipeline.score", _score)
        registry.register("credit_pipeline.parse", _parse)
        registry.register("credit_pipeline.decide", _decide)

        logger.info(
            "credit_pipeline: 3 actions registered "
            "(credit_pipeline.{score,parse,decide})"
        )

    async def on_register_repositories(
        self, registry: RepositoryRegistryProtocol
    ) -> None:
        """Defer: DB repository hooks для credit_applications / reports."""

    async def on_register_processors(self, registry: ProcessorRegistryProtocol) -> None:
        """Defer: DSL processors не требуются (actions достаточно)."""

    async def on_shutdown(self) -> None:
        """Логирует факт выключения плагина."""
        logger.info("credit_pipeline v%s shutdown", self.version)
