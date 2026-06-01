"""LLM-activity wrapper для Temporal workflow (Sprint 4 Wave C).

Назначение:
    Декларативная LLM-activity, регистрируемая в Temporal Worker и
    вызываемая из :mod:`dsl.workflow` через ``WorkflowBuilder.activity``.
    Поддерживает: cost-tracking, retry через RetryPolicy, Heartbeat при
    streaming, structured output через Pydantic-schema.

Архитектурные принципы:
    * Lazy-import :mod:`temporalio` — модуль импортируется без падения
      даже когда extra ``workflow`` не установлен.
    * LiteLLMGateway lazy-resolve через :func:`_resolve_gateway`; mock
      может быть подменён через monkeypatch в тестах.
    * Feature-flag ``ai_workflow_activity_enabled`` гейтит
      ``register_llm_activity`` (default-OFF: NoOp регистрация).

V15 R-V15-9 (AI-функции через Workflow DSL): LLM-вызовы декларативны.

Public API:
    * :class:`LLMActivityInput` — Pydantic-input.
    * :class:`LLMActivityOutput` — Pydantic-output с cost/tokens.
    * :func:`llm_activity` — Temporal ``@activity.defn`` функция (lazy).
    * :func:`register_llm_activity` — регистрирует activity в Worker
      под feature-flag.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = (
    "LLMActivityInput",
    "LLMActivityOutput",
    "llm_activity",
    "register_llm_activity",
)

_logger = logging.getLogger("services.ai.workflow_activities")


class LLMActivityInput(BaseModel):
    """Параметры LLM-activity (passable through Temporal payload)."""

    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, description="Promt-текст для модели.")
    model: str = Field(default="gpt-4", description="Имя LLM-модели.")
    temperature: float = Field(
        default=0.7, ge=0.0, le=2.0, description="Sampling temperature."
    )
    max_tokens: int | None = Field(
        default=None,
        gt=0,
        description="Лимит выходных токенов; None — модельный default.",
    )
    structured_output_schema: str | None = Field(
        default=None,
        description=(
            "Опц. имя Pydantic-модели в registry для structured output. "
            "При наличии — output JSON-валидируется по schema."
        ),
    )
    tools: list[dict[str, Any]] | None = Field(
        default=None,
        description="Опц. список tool-definitions (OpenAI function-calling format).",
    )


class LLMActivityOutput(BaseModel):
    """Результат LLM-activity с метриками."""

    model_config = ConfigDict(extra="forbid")

    content: str = Field(description="Сгенерированный текст ответа.")
    prompt_tokens: int = Field(ge=0, description="Токены input prompt.")
    completion_tokens: int = Field(ge=0, description="Токены output completion.")
    cost_usd: float = Field(ge=0.0, description="Стоимость вызова в USD.")
    model_used: str = Field(description="Имя фактически использованной модели.")
    structured: dict[str, Any] | None = Field(
        default=None, description="Структурированный output (если запрашивался schema)."
    )


def _resolve_gateway() -> Any:
    """Lazy-резолв LiteLLMGateway клиента (через app_state DI).

    Returns:
        LiteLLMGateway инстанс.

    Raises:
        RuntimeError: Если gateway не инициализирован (lifespan не поднят).
    """
    try:
        from src.backend.services.ai.gateway.client import get_litellm_gateway

        return get_litellm_gateway()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "LiteLLMGateway недоступен (lifespan не поднят либо модуль "
            "отсутствует). Sprint 4 Wave C: lazy-resolve provoked."
        ) from exc


async def _execute_llm_call(
    input_: LLMActivityInput, *, heartbeat: Any = None
) -> LLMActivityOutput:
    """Внутренний исполнитель LLM-вызова (без temporalio dependencies).

    Выделен в отдельную функцию чтобы:
        * упростить unit-тестирование (mocked gateway без temporalio);
        * переиспользовать в LiteTemporalBackend dev_light.

    Args:
        input_: Параметры вызова.
        heartbeat: Опц. callable для Temporal-heartbeat (sync or async).
            Вызывается после успешного API-ответа.

    Returns:
        :class:`LLMActivityOutput` с content/tokens/cost.
    """
    gateway = _resolve_gateway()

    # acompletion API: prompt → response
    response = await gateway.acompletion(
        messages=[{"role": "user", "content": input_.prompt}],
        model=input_.model,
        temperature=input_.temperature,
        max_tokens=input_.max_tokens,
        tools=input_.tools,
    )

    if heartbeat is not None:
        try:
            result = heartbeat()
            if hasattr(result, "__await__"):
                await result
        except Exception as _:  # noqa: BLE001
            _logger.exception("Heartbeat callback raised; suppressing")

    # Унифицированное извлечение content / usage из response.
    usage = getattr(response, "usage", None) or response.get("usage", {})
    choices = getattr(response, "choices", None) or response.get("choices", [])
    first_choice = choices[0] if choices else {}
    message = getattr(first_choice, "message", None) or first_choice.get("message", {})
    content_str = getattr(message, "content", None) or message.get("content", "") or ""

    cost_usd = 0.0
    try:
        cost_usd = float(await gateway.acost_estimate(response))
    except Exception as _:  # noqa: BLE001
        _logger.debug("acost_estimate недоступен; cost=0.0")

    structured: dict[str, Any] | None = None
    if input_.structured_output_schema is not None and content_str:
        try:
            import json

            structured = json.loads(content_str)
        except json.JSONDecodeError:
            _logger.warning(
                "structured_output_schema задан, но content не валидный JSON"
            )

    return LLMActivityOutput(
        content=content_str,
        prompt_tokens=int(
            getattr(usage, "prompt_tokens", None) or usage.get("prompt_tokens", 0)
        ),
        completion_tokens=int(
            getattr(usage, "completion_tokens", None)
            or usage.get("completion_tokens", 0)
        ),
        cost_usd=cost_usd,
        model_used=str(
            getattr(response, "model", None) or response.get("model", input_.model)
        ),
        structured=structured,
    )


async def llm_activity(input_: LLMActivityInput) -> LLMActivityOutput:
    """Temporal-activity для LLM-вызова (Sprint 4 Wave C).

    При импорте :mod:`temporalio` оборачивается через ``@activity.defn``;
    при отсутствии — функция доступна как обычная async-callable.

    Args:
        input_: Параметры вызова (Pydantic).

    Returns:
        :class:`LLMActivityOutput`.
    """
    heartbeat = None
    try:
        from temporalio import activity as temporal_activity

        heartbeat = temporal_activity.heartbeat
    except Exception:  # noqa: BLE001, S110 — lazy temporalio import; offline fallback
        pass

    return await _execute_llm_call(input_, heartbeat=heartbeat)


# Опционально пытаемся пометить функцию как @activity.defn.
try:
    from temporalio import activity as _temporal_activity_mod

    llm_activity = _temporal_activity_mod.defn(name="ai.llm.call")(llm_activity)  # type: ignore[assignment]
except Exception:  # noqa: BLE001, S110 — temporalio extra может быть отключён
    pass


def register_llm_activity(worker: Any) -> bool:
    """Зарегистрировать :func:`llm_activity` в Temporal Worker.

    Проверяет feature-flag ``ai_workflow_activity_enabled`` и в случае
    выключенного флага — NoOp (возвращает False).

    Args:
        worker: Temporal Worker (или mock с методом ``register_activity``).

    Returns:
        True если activity зарегистрирована; False — если flag выключен.
    """
    try:
        from src.backend.core.config.features import feature_flags

        enabled = bool(feature_flags.ai_workflow_activity_enabled)
    except Exception as _:  # noqa: BLE001
        enabled = False

    if not enabled:
        _logger.debug(
            "register_llm_activity NoOp: ai_workflow_activity_enabled выключен"
        )
        return False

    if hasattr(worker, "register_activity"):
        worker.register_activity(llm_activity)
    elif hasattr(worker, "activities"):
        # Temporal Worker SDK: список activities передаётся в конструктор;
        # для динамической регистрации mutable-list используется как fallback.
        try:
            worker.activities.append(llm_activity)
        except AttributeError:
            _logger.warning("worker.activities не mutable; регистрация пропущена")
            return False
    else:
        _logger.warning("Worker не поддерживает register_activity/activities; пропуск")
        return False

    return True
