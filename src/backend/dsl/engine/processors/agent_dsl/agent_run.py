"""AgentRunProcessor — DSL-вызов :class:`AIGateway.invoke` (S27 W1).

Декларативный шаг для вызова LLM-агента через :class:`AIGateway` (ADR-NEW-19).
Caller указывает ``workflow_id``, ``prompt_ref`` (или ``prompt_inline``),
опц. ``context_property``; процессор резолвит :class:`AIGateway` через DI,
вызывает :meth:`AIGateway.invoke`, записывает :class:`AIResponse` в
``exchange.properties[result_property]``.

YAML контракт::

    steps:
      - agent_run:
          workflow_id: credit_check
          prompt_ref: credit_check.production
          policy_ref: credit_check_strict
          context_property: body.context
          result_property: agent_result

Python контракт через :meth:`AgentDSLMixin.agent_run`::

    builder.agent_run(
        workflow_id="credit_check",
        prompt_ref="credit_check.production",
        context_property="body.context",
    )
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.dsl.engine.processors.agent_dsl._base import BaseAIProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("AgentRunProcessor",)

_logger = logging.getLogger(__name__)


class AgentRunProcessor(BaseAIProcessor):
    """Вызвать :class:`AIGateway.invoke` по ``workflow_id`` + prompt.

    Args:
        workflow_id: Идентификатор бизнес-операции
            (``"credit_check"``, ``"doc_summarize"``).
        prompt_ref: Ссылка на промпт в Langfuse PromptRegistry.
            Взаимоисключаемо с ``prompt_inline``.
        prompt_inline: Inline-промпт без registry-маршрутизации.
            Используется при отсутствии prompt registry.
        policy_ref: Опциональная ссылка на :class:`AIPolicySpec`
            (``"credit_check_strict"``). Резолв политики выполняется
            :class:`PolicyResolver` внутри :class:`AIGateway` — здесь
            это только metadata для downstream-консумеров.
        context_property: Путь к переменным template из ``exchange``
            (по умолчанию — ``"body"``, что означает ``exchange.in_message.body``
            как ``dict``-context).
        result_property: Свойство, куда записать результат (default
            ``"agent_result"``).
        name: Имя процессора.

    Result в exchange:
        ``exchange.properties[result_property]`` = dict с полями:
        ``{"content": str, "structured": Any | None, "tokens_prompt": int,
          "tokens_completion": int, "cost_usd": float, "model_used": str,
          "pii_detected": bool, "guardrails_verdict": dict}``.
    """

    required_capability: ClassVar[str | None] = "ai.invoke"
    audit_event: ClassVar[str | None] = "ai.agent.run"

    def __init__(
        self,
        *,
        workflow_id: str,
        prompt_ref: str | None = None,
        prompt_inline: str | None = None,
        policy_ref: str | None = None,
        context_property: str | None = "body",
        result_property: str = "agent_result",
        name: str | None = None,
    ) -> None:
        if not workflow_id:
            raise ValueError("AgentRunProcessor: workflow_id обязателен")
        if prompt_ref is None and prompt_inline is None:
            raise ValueError(
                "AgentRunProcessor: требуется prompt_ref или prompt_inline"
            )
        super().__init__(name=name or f"agent_run:{workflow_id}")
        self.workflow_id = workflow_id
        self.prompt_ref = prompt_ref
        self.prompt_inline = prompt_inline
        self.policy_ref = policy_ref
        self.context_property = context_property
        self.result_property = result_property

    def _capability_scope(self, exchange: "Exchange[Any]") -> str | None:
        """Scope для ``ai.invoke`` = ``workflow_id`` (см. ADR-NEW-19)."""
        del exchange
        return self.workflow_id

    async def _run(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        del context
        from src.backend.core.ai.gateway import AIRequest

        gateway = self._resolve_gateway()
        if gateway is None:
            exchange.set_error(
                f"{self.name}: AIGateway не найден в DI — нельзя выполнить invoke"
            )
            exchange.stop()
            return

        request = AIRequest(
            workflow_id=self.workflow_id,
            tenant_id=exchange.meta.tenant_id or "unknown",
            correlation_id=exchange.meta.correlation_id,
            prompt_ref=self.prompt_ref,
            prompt_inline=self.prompt_inline,
            context=self._extract_context(exchange),
        )
        response = await gateway.invoke(request)

        exchange.set_property(
            self.result_property,
            {
                "content": getattr(response, "content", ""),
                "structured": getattr(response, "structured", None),
                "tokens_prompt": getattr(response, "tokens_prompt", 0),
                "tokens_completion": getattr(response, "tokens_completion", 0),
                "cost_usd": getattr(response, "cost_usd", 0.0),
                "model_used": getattr(response, "model_used", ""),
                "pii_detected": getattr(response, "pii_detected", False),
                "guardrails_verdict": dict(
                    getattr(response, "guardrails_verdict", {}) or {}
                ),
                "policy_ref": self.policy_ref,
            },
        )

    def _extract_context(self, exchange: "Exchange[Any]") -> dict[str, Any]:
        """Достать context для template из exchange.

        Поддерживает простые пути: ``"body"`` → ``exchange.in_message.body``;
        ``"body.context"`` → ``exchange.in_message.body.get("context")``;
        ``"property:my_prop"`` → ``exchange.get_property("my_prop")``.
        """
        if self.context_property is None:
            return {}
        path = self.context_property
        if path.startswith("property:"):
            value = exchange.get_property(path[len("property:") :], {})
            return value if isinstance(value, dict) else {"value": value}
        if path == "body":
            body = exchange.in_message.body
            return body if isinstance(body, dict) else {"body": body}
        if path.startswith("body."):
            body = exchange.in_message.body
            if not isinstance(body, dict):
                return {}
            key = path[len("body.") :]
            value = body.get(key, {})
            return value if isinstance(value, dict) else {"value": value}
        return {}

    @staticmethod
    def _resolve_gateway() -> Any | None:
        """Lazy-резолв :class:`AIGateway` через DI singleton."""
        try:
            from src.backend.services.ai.gateway_adapter import get_ai_gateway

            return get_ai_gateway()
        except Exception as _:  # noqa: BLE001
            try:
                from src.backend.core.di.container import get_container

                container = get_container()
                if container is not None:
                    return container.resolve_optional("ai_gateway")
            except Exception as exc:  # noqa: BLE001
                _logger.debug("AgentRunProcessor: DI container resolve failed: %s", exc)
        return None

    def to_spec(self) -> dict[str, Any]:
        """Round-trip сериализация для YAML."""
        spec: dict[str, Any] = {"workflow_id": self.workflow_id}
        if self.prompt_ref is not None:
            spec["prompt_ref"] = self.prompt_ref
        if self.prompt_inline is not None:
            spec["prompt_inline"] = self.prompt_inline
        if self.policy_ref is not None:
            spec["policy_ref"] = self.policy_ref
        if self.context_property != "body":
            spec["context_property"] = self.context_property
        if self.result_property != "agent_result":
            spec["result_property"] = self.result_property
        return {"agent_run": spec}
