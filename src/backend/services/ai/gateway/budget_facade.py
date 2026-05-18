"""LiteLLM Budget Facade — token budget enforcement (Sprint 9 K4 W2).

Wrapper над :class:`LiteLLMGateway`, который:

#. Оценивает токены ``estimate_tokens(messages)`` до вызова;
#. Резервирует через :class:`TokenBudget` (``enforce_pre_call``);
#. Выполняет ``acompletion``;
#. Корректирует фактическим usage'ом из ответа (``enforce_post_call``);
#. При :class:`BudgetExceeded` возвращает :class:`BudgetEnforcementError`
   для маппинга в 429 в endpoint-слое.

Feature-flag: ``feature_flags.tenant_token_budget_enabled`` (default-OFF
до завершения rollout — см. Sprint 9 backbone).
"""

from __future__ import annotations

import logging
from typing import Any

from src.backend.core.tenancy.budget_enforcer import (
    enforce_post_call,
    enforce_pre_call,
)
from src.backend.core.tenancy.token_budget import BudgetExceeded, TokenBudget
from src.backend.services.ai.usage_meter import (
    UsageStats,
    estimate_tokens,
    extract_usage,
)

__all__ = ("LiteLLMBudgetFacade", "BudgetEnforcementError")

logger = logging.getLogger(__name__)


class BudgetEnforcementError(Exception):
    """Поднимается endpoint-слою для маппинга в 429.

    Attributes:
        body: JSON-ready payload (см. :func:`render_429`).
    """

    def __init__(self, *, body: dict[str, Any]) -> None:
        super().__init__(body.get("message", "token_budget_exceeded"))
        self.body = body


class LiteLLMBudgetFacade:
    """Wraps LiteLLMGateway с per-tenant token budget.

    Args:
        gateway: реальный :class:`LiteLLMGateway` (с acompletion).
        budget: :class:`TokenBudget`.
        enabled: feature-flag (если False — proxy без enforcement).
    """

    def __init__(
        self,
        *,
        gateway: Any,
        budget: TokenBudget,
        enabled: bool = True,
    ) -> None:
        self._gateway = gateway
        self._budget = budget
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def acompletion(
        self,
        *,
        tenant_id: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> tuple[Any, UsageStats]:
        """Chat-completion с token-budget enforcement.

        Returns:
            ``(response, usage_stats)`` — response как из LiteLLM,
            usage_stats извлечён через :func:`extract_usage`.

        Raises:
            BudgetEnforcementError: hard_limit превышен (caller → 429).
        """
        if not self._enabled:
            response = await self._gateway.acompletion(messages, **kwargs)
            return response, extract_usage(response)

        from src.backend.core.tenancy.budget_enforcer import render_429

        estimated = estimate_tokens(messages)
        try:
            await enforce_pre_call(
                budget=self._budget,
                tenant_id=tenant_id,
                estimated_tokens=estimated,
            )
        except BudgetExceeded as exc:
            logger.warning(
                "llm.budget.exceeded.pre",
                extra={
                    "tenant_id": tenant_id,
                    "used": exc.used,
                    "hard_limit": exc.hard_limit,
                },
            )
            raise BudgetEnforcementError(body=render_429(exc)) from exc

        response = await self._gateway.acompletion(messages, **kwargs)
        usage = extract_usage(response)
        try:
            await enforce_post_call(
                budget=self._budget,
                tenant_id=tenant_id,
                estimated_tokens=estimated,
                actual_tokens=usage.total_tokens,
            )
        except BudgetExceeded as exc:
            logger.warning(
                "llm.budget.exceeded.post",
                extra={
                    "tenant_id": tenant_id,
                    "actual_tokens": usage.total_tokens,
                    "hard_limit": exc.hard_limit,
                },
            )
            raise BudgetEnforcementError(body=render_429(exc)) from exc
        return response, usage
