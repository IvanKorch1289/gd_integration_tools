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
          timeout_s: 120
          max_retries: 3

Python контракт через :meth:`AgentDSLMixin.agent_run`::

    builder.agent_run(
        workflow_id="credit_check",
        prompt_ref="credit_check.production",
        context_property="body.context",
        timeout_s=120,
        max_retries=3,
    )
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.agent_dsl._base import BaseAIProcessor
from src.backend.services.ai.gateway.exceptions import GatewayUnavailable

if TYPE_CHECKING:
    from src.backend.core.ai.gateway import AIRequest
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("AgentRunProcessor",)

_logger = get_logger(__name__)


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
        timeout_s: Timeout на вызов в секундах (default 300).
            При превышении — ``ExchangeStatus.failed`` с error.
        max_retries: Число повторных попыток при transient failure (default 3).
            Retry выполняется до ``timeout_s`` совокупно.
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
        timeout_s: float = 300.0,
        max_retries: int = 3,
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
        self.timeout_s = timeout_s
        self.max_retries = max_retries

    def _capability_scope(self, exchange: Exchange[Any]) -> str | None:
        """Scope для ``ai.invoke`` = ``workflow_id`` (см. ADR-NEW-19)."""
        del exchange
        return self.workflow_id

    async def _run(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        _ = context  # Зарезервировано для майбутнього use (correlation, tenant_id)
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

        try:
            if self.max_retries > 0:
                response = await self._invoke_with_retry(gateway, request)
            else:
                response = await asyncio.wait_for(
                    gateway.invoke(request), timeout=self.timeout_s
                )
        except TimeoutError:
            exchange.set_error(
                f"{self.name}: timeout ({self.timeout_s}s) при вызове AIGateway.invoke"
            )
            exchange.stop()
            return
        except Exception as exc:
            _logger.warning(
                "%s: AIGateway.invoke failed: %s", self.name, exc, exc_info=True
            )
            exchange.set_error(f"{self.name}: AIGateway.invoke error: {exc}")
            exchange.stop()
            return

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

    async def _invoke_with_retry(self, gateway: Any, request: AIRequest) -> Any:
        """Retry-обёртка над gateway.invoke с exponential backoff.

        Retry на transient exceptions (GatewayUnavailable, network errors,
        TimeoutError). Не retry на CapabilityDeniedError, PolicyNotResolvedError.
        """
        import tenacity

        async def _call() -> Any:
            return await asyncio.wait_for(
                gateway.invoke(request), timeout=self.timeout_s
            )

        retry = tenacity.AsyncRetrying(
            retry=tenacity.retry_if_exception_type(
                (GatewayUnavailable, OSError, TimeoutError)
            ),
            wait=tenacity.wait_exponential(multiplier=1.0, min=1.0, max=30.0),
            stop=tenacity.stop_after_attempt(self.max_retries),
            reraise=True,
        )
        async for attempt in retry:
            with attempt:
                return await _call()
        return None

    def _extract_context(self, exchange: Exchange[Any]) -> dict[str, Any]:
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
            from src.backend.services.ai.gateway_adapter import (  # type: ignore[attr-defined]
                get_ai_gateway,
            )

            return get_ai_gateway()
        except ImportError, AttributeError, RuntimeError:
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
        if self.timeout_s != 300.0:
            spec["timeout_s"] = self.timeout_s
        if self.max_retries != 3:
            spec["max_retries"] = self.max_retries
        return {"agent_run": spec}
