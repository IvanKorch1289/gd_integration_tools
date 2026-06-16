"""Базовый класс typed-агентов поверх PydanticAI + LiteLLMGateway.

Sprint 3 W1 К4 Шаг 3: добавлен prod-config (retry / fallback model /
structured-output strict) с lazy-применением через tenacity. Совместим с
PydanticAI 0.5.x — внутренний API ``Agent.run`` не изменён.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ValidationError

from src.backend.core.logging import get_logger

logger = get_logger(__name__)

__all__ = (
    "AgentRetryConfig",
    "BasePydanticAgent",
    "ModelSpec",
    "PydanticAIUnavailable",
    "ResultT",
)

ResultT = TypeVar("ResultT", bound=BaseModel)

# Какие классы исключений считаются "transient" и переотправляются.
# httpx/openai timeout/network ошибки + pydantic_ai run-time ошибки.
_TRANSIENT_EXCEPTION_NAMES: tuple[str, ...] = (
    "TimeoutError",
    "ConnectError",
    "ConnectTimeout",
    "ReadTimeout",
    "RemoteProtocolError",
    "APIConnectionError",
    "APITimeoutError",
    "InternalServerError",
)


def _is_transient(exc: BaseException) -> bool:
    """Эвристика: распознаём network / timeout / 5xx как retry-кандидат.

    Импорт конкретных классов сетевых ошибок зависит от установленных
    extras (httpx / openai / anthropic). Чтобы не привязываться к
    конкретному стэку, сравниваем по имени класса.
    """
    name = type(exc).__name__
    if name in _TRANSIENT_EXCEPTION_NAMES:
        return True
    # Для pydantic_ai run-time ошибок: считаем transient всё, что не
    # ValidationError и не TypeError.
    return not isinstance(exc, ValidationError | TypeError | ValueError)


class PydanticAIUnavailable(RuntimeError):
    """``pydantic_ai`` не установлен — добавьте extra '[ai-2026]'."""


@dataclass(slots=True, frozen=True)
class AgentRetryConfig:
    """Параметры retry-стратегии агента.

    Attrs:
        max_attempts: Общее число попыток (включая первую).
        backoff: Тип backoff'а: ``exponential`` (по умолчанию) или ``fixed``.
        jitter: Добавлять случайный jitter (полный) к backoff.
        initial_seconds: Базовая задержка между попытками.
        max_seconds: Верхняя граница задержки между попытками.
    """

    max_attempts: int = 3
    backoff: Literal["exponential", "fixed"] = "exponential"
    jitter: bool = True
    initial_seconds: float = 1.0
    max_seconds: float = 30.0


@dataclass(slots=True, frozen=True)
class ModelSpec:
    """Спецификация fallback-модели (минимально: имя; gateway тот же)."""

    model_name: str
    system_prompt_override: str | None = None


@dataclass(slots=True)
class _AgentRuntimeState:
    """Внутреннее состояние: lazy-агент + текущий fallback-флаг."""

    agent: Any = None
    using_fallback: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


class BasePydanticAgent(Generic[ResultT]):
    """Базовая обёртка над ``pydantic_ai.Agent`` с типизированным результатом.

    Args:
        result_type: Pydantic-модель ожидаемого результата.
        system_prompt: Системный prompt агента.
        model_name: Имя primary-модели (LiteLLM-формат, например
            ``openai/gpt-4o-mini``).
        gateway: Готовый :class:`LiteLLMGateway`; по умолчанию резолвится
            через DI (:func:`get_litellm_gateway`).
        retry_config: Параметры retry-стратегии (transient errors).
            ``None`` → одна попытка без retry.
        fallback_model: Спецификация резервной модели при провале primary
            после всех retry. ``None`` → fallback выключен.
        structured_output: Если ``True`` (default) — на :class:`ValidationError`
            вызывается ``on_validation_error``-handler (raise / fallback).
        on_validation_error: ``fail`` (default — пробросить ошибку) или
            ``fallback`` (попытаться через fallback_model). ``warn`` —
            залогировать и вернуть результат как есть.

    Sprint 4 уберёт adapter-shim ``LiteLLMModel`` и привяжет
    ``pydantic_ai_litellm`` напрямую.
    """

    result_type: type[BaseModel]

    def __init__(
        self,
        *,
        result_type: type[ResultT] | None = None,
        system_prompt: str = "",
        model_name: str | None = None,
        gateway: Any | None = None,
        retry_config: AgentRetryConfig | None = None,
        fallback_model: ModelSpec | None = None,
        structured_output: bool = True,
        on_validation_error: Literal["fail", "fallback", "warn"] = "fail",
    ) -> None:
        if result_type is not None:
            self.result_type = result_type
        if not hasattr(self, "result_type"):
            raise TypeError(
                "BasePydanticAgent: укажите result_type=PydanticModel либо "
                "переопределите атрибут класса."
            )
        self._system_prompt = system_prompt
        self._model_name = model_name
        self._gateway = gateway
        self._retry_config = retry_config
        self._fallback_model = fallback_model
        self._structured_output = structured_output
        self._on_validation_error = on_validation_error
        self._state = _AgentRuntimeState()

    # ------------------------------------------------------------------
    # Lazy-construction (PydanticAI + LiteLLM gateway).
    # ------------------------------------------------------------------

    def _ensure_gateway(self) -> Any:
        if self._gateway is not None:
            return self._gateway
        # S85 W2 (V2 P0 #1): pre-flight enforcement check.
        # Bypass через LiteLLMGateway запрещён. Если ai_gateway_enforce=False
        # — бросаем AIGatewayEnforcementRequiredError.
        from src.backend.core.ai.errors import AIGatewayEnforcementRequiredError
        from src.backend.core.config.features import feature_flags

        if not feature_flags.ai_gateway_enforce:
            raise AIGatewayEnforcementRequiredError(
                "agents_pydantic.BasePydanticAgent requires ai_gateway_enforce=True "
                "(S85 W2: bypass via LiteLLMGateway is no longer supported)"
            )
        from src.backend.services.ai.gateway.client import get_litellm_gateway

        self._gateway = get_litellm_gateway()
        return self._gateway

    def _build_agent(self, model_name: str | None, system_prompt: str | None) -> Any:
        """Создаёт ``pydantic_ai.Agent`` с указанной моделью/prompt."""
        try:
            from pydantic_ai import Agent
        except ImportError as exc:
            raise PydanticAIUnavailable(
                "pydantic-ai не установлен — добавьте extra '[ai-2026]'."
            ) from exc

        from src.backend.services.ai.agents_pydantic.adapter import LiteLLMModel

        gateway = self._ensure_gateway()
        model = LiteLLMModel(gateway=gateway, model_name=model_name)
        return Agent(
            model=model,
            result_type=self.result_type,
            system_prompt=system_prompt or self._system_prompt,
        )

    def _ensure_agent(self) -> Any:
        """Lazy-создание primary-агента (с кэшированием)."""
        if self._state.agent is not None and not self._state.using_fallback:
            return self._state.agent
        self._state.agent = self._build_agent(self._model_name, self._system_prompt)
        self._state.using_fallback = False
        return self._state.agent

    def _build_fallback_agent(self) -> Any:
        """Конструирует fallback-агента (с другой моделью / prompt)."""
        if self._fallback_model is None:
            raise RuntimeError("fallback_model не сконфигурирован")
        agent = self._build_agent(
            self._fallback_model.model_name,
            self._fallback_model.system_prompt_override or self._system_prompt,
        )
        return agent

    # ------------------------------------------------------------------
    # Retry + fallback wrapper.
    # ------------------------------------------------------------------

    async def _retry_call(self, agent: Any, user_input: str, deps: Any) -> Any:
        """Выполняет ``agent.run`` с retry'ами при transient errors.

        Использует tenacity, если задан :attr:`_retry_config`. На
        validation-error retry не применяется (нет смысла пере-запрашивать
        тот же prompt — модель отвечает структурно-неверно).
        """
        if self._retry_config is None:
            return await agent.run(user_input, deps=deps)

        from tenacity import (
            AsyncRetrying,
            RetryError,
            retry_if_exception,
            stop_after_attempt,
            wait_exponential_jitter,
            wait_fixed,
        )

        cfg = self._retry_config
        if cfg.backoff == "exponential":
            wait = wait_exponential_jitter(
                initial=cfg.initial_seconds,
                max=cfg.max_seconds,
                jitter=cfg.initial_seconds if cfg.jitter else 0,
            )
        else:
            wait = wait_fixed(cfg.initial_seconds)

        retryer = AsyncRetrying(
            stop=stop_after_attempt(cfg.max_attempts),
            wait=wait,
            retry=retry_if_exception(_is_transient),
            reraise=True,
        )
        try:
            async for attempt in retryer:
                with attempt:
                    return await agent.run(user_input, deps=deps)
        except RetryError as exc:
            raise exc.last_attempt.exception() or RuntimeError(
                "Retry exhausted"
            ) from exc
        # Не должно быть достигнуто — AsyncRetrying либо возвращает,
        # либо бросает.
        raise RuntimeError("AsyncRetrying завершился без результата")

    async def run(self, user_input: str, **deps: Any) -> ResultT:
        """Запускает агента и возвращает строго-типизированный результат.

        Last-resort fallback: при провале primary после всех retry —
        попытка через :attr:`_fallback_model`. На :class:`ValidationError`
        поведение определяется :attr:`_on_validation_error`.

        Args:
            user_input: Пользовательский запрос.
            **deps: Дополнительные deps для tool-calls.

        Returns:
            Экземпляр :attr:`result_type`.

        Raises:
            PydanticAIUnavailable: если ``pydantic_ai`` не установлен.
            ValidationError: при ``on_validation_error="fail"``.
            Exception: пробрасываются исключения, не классифицированные
                как transient (TypeError, ValueError и т.д.).
        """
        deps_arg = deps if deps else None
        primary = self._ensure_agent()
        try:
            result = await self._retry_call(primary, user_input, deps_arg)
        except ValidationError:
            return await self._handle_validation_error(user_input, deps_arg)
        except Exception as exc:
            if self._fallback_model is None:
                raise
            logger.warning(
                "Primary-агент %s failed (%s) — переключаемся на fallback %s",
                self._model_name,
                type(exc).__name__,
                self._fallback_model.model_name,
            )
            fallback = self._build_fallback_agent()
            self._state.using_fallback = True
            result = await self._retry_call(fallback, user_input, deps_arg)
        return self._coerce_result(result)

    async def _handle_validation_error(self, user_input: str, deps_arg: Any) -> ResultT:
        """Обрабатывает ValidationError по policy ``on_validation_error``."""
        match self._on_validation_error:
            case "fail":
                raise
            case "warn":
                logger.warning(
                    "ValidationError в %s, возвращаем последний raw-результат",
                    self._model_name,
                )
                raise
            case "fallback":
                if self._fallback_model is None:
                    raise
                logger.warning(
                    "Validation failure — switching to fallback %s",
                    self._fallback_model.model_name,
                )
                fallback = self._build_fallback_agent()
                self._state.using_fallback = True
                result = await self._retry_call(fallback, user_input, deps_arg)
                return self._coerce_result(result)
            case _:
                raise

    def _coerce_result(self, raw: Any) -> ResultT:
        """Извлекает strict-типизированный объект из PydanticAI-ответа."""
        data = getattr(raw, "data", raw)
        if isinstance(data, self.result_type):
            return data  # type: ignore[return-value]
        if self._structured_output:
            return self.result_type.model_validate(data)  # type: ignore[return-value]
        # Если structured_output=False — возвращаем как есть (best-effort).
        return data
