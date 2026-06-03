"""AIRequest/AIResponse dataclasses для AIGateway (S38 P1.1b circular fix).

Извлечено из ``core/ai/gateway.py`` для разрыва circular import:
- gateway.py → gateway_pipeline_mixin.py (PipelineStepsMixin)
- gateway_pipeline_mixin.py → gateway.py (AIRequest, AIResponse)

Оба файла теперь импортируют модели из этого модуля, без cycle.

Backward compat: импорт ``from src.backend.core.ai.gateway import AIRequest, AIResponse``
продолжает работать через re-export в gateway.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ("AIRequest", "AIResponse")


@dataclass(frozen=True, slots=True)
class AIRequest:
    """Запрос на AI-инвокацию.

    Передаётся в :meth:`AIGateway.invoke`. Поля заполняются caller'ом из
    :class:`RequestContext` (ADR-NEW-3) — ``correlation_id`` и ``tenant_id``
    обязательны для аудит-связки.

    Attributes:
        workflow_id: Логический идентификатор бизнес-операции
            (``"credit_check"``, ``"doc_summarize"``). Используется
            :class:`PolicyResolver` для подбора :class:`AIPolicySpec`.
        tenant_id: Tenant из ``TenantContext``; контекст PII / quotas / SLO.
        correlation_id: Идентификатор запроса из ``RequestContext`` для
            аудит-trace; пробрасывается во все sinks (ClickHouse, Langfuse).
        prompt_ref: Ссылка на промпт в Langfuse PromptRegistry
            (``"credit_check.production"``). Взаимоисключаемо с ``prompt_inline``.
        prompt_inline: Inline-промпт без registry-маршрутизации (deprecated
            путь для legacy кодопутей; S27 closure → запрещено).
        context: Переменные подстановки в template (Jinja2 / f-string).
        stream: Если ``True`` — стриминг chunks (SSE/WebSocket).
    """

    workflow_id: str
    tenant_id: str
    correlation_id: str
    prompt_ref: str | None = None
    prompt_inline: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    stream: bool = False


@dataclass(frozen=True, slots=True)
class AIResponse:
    """Результат AI-инвокации.

    Attributes:
        content: Финальный (sanitized) текст ответа LLM.
        structured: Опциональный Pydantic-объект, если использован
            Instructor / Outlines structured output.
        tokens_prompt: Токены входа после template-render и budget-trim.
        tokens_completion: Токены ответа LLM.
        cost_usd: Стоимость инвокации в USD (через ``ai_cost_tracker``).
        model_used: Фактическая модель, выбранная ``ModelRouter`` из
            fallback chain (может отличаться от ``policy.model_router.primary``).
        pii_detected: ``True`` если хотя бы один PII entity обнаружен
            на стадии input/output sanitizers.
        guardrails_verdict: ``{"input": "safe", "output": "safe|blocked|warn"}``
            от input/output guards (NeMo + Llama Guard).
    """

    content: str
    structured: Any | None = None
    tokens_prompt: int = 0
    tokens_completion: int = 0
    cost_usd: float = 0.0
    model_used: str = ""
    pii_detected: bool = False
    guardrails_verdict: dict[str, str] = field(default_factory=dict)
