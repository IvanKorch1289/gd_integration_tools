"""DSL-шаг ``ai_rpa`` — AI-driven RPA action decision via LLM.

Wave: ``[wave:s8/k3-rpa-ai-decide]``. Использует LLM для анализа UI-состояния
и выбора оптимального RPA действия (click/type/screenshot) на основе описания задачи.

Использование (Python builder)::

    builder.ai_rpa(
        task="Нажми кнопку 'Подтвердить' в диалоговом окне",
        ui_context={"screenshot": "${rpa.screenshot}"},
        action_property="ai_rpa.action",
        to="property:rpa.last_action",
    )

YAML::

    - ai_rpa:
        task: "Нажми кнопку 'Подтвердить'"
        ui_context:
          screenshot: "${rpa.screenshot}"
        action_property: "ai_rpa.action"
        to: property:rpa.last_action
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field, ValidationError

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("AIRpaProcessor",)

_logger = get_logger(__name__)

_VALID_ACTIONS = frozenset({"click", "type", "screenshot", "hover", "scroll", "wait"})


class RPAAction(BaseModel):
    """Structured output schema for AI RPA action."""

    action: Literal["click", "type", "screenshot", "hover", "scroll", "wait"] = Field(
        ..., description="RPA action to perform"
    )
    params: dict[str, Any] = Field(
        default_factory=dict, description="Action parameters"
    )
    reasoning: str = Field(default="", description="LLM reasoning for the action")


@processor(name="ai_rpa")
class AIRpaProcessor(BaseProcessor):
    """AI-driven RPA action selector.

    Анализирует задачу (natural language) и UI-контекст (screenshot/dom_snapshot)
    через LLM и возвращает структурированный RPA action для последующего
    выполнения через DesktopRpaProcessor или BrowserRpaProcessor.

    Args:
        task: Описание задачи на естественном языке.
        ui_context: Dict с UI-данными (``screenshot``, ``dom_snapshot``, ``element_info``).
        action_property: Exchange property для записи выбранного action.
        model: LLM model для принятия решений (default ``gpt-4o``).
        temperature: Temperature для LLM (default ``0.1``).
        to: Опц. путь записи результата (``body.<field>`` / ``property:<name>``).
        name: Имя процессора для трейсов.
        max_retries: Максимальное количество retry при невалидном ответе (default 3).
    """

    name = "ai_rpa"
    side_effect = SideEffectKind.SIDE_EFFECTING
    compensatable = False

    def __init__(
        self,
        *,
        task: str,
        ui_context: dict[str, Any] | None = None,
        action_property: str = "ai_rpa.action",
        model: str = "gpt-4o",
        temperature: float = 0.1,
        to: str = "property:rpa.ai_decision",
        name: str | None = None,
        max_retries: int = 3,
    ) -> None:
        super().__init__(name=name or self.name)
        self._task = task
        self._ui_context = dict(ui_context or {})
        self._action_property = action_property
        self._model = model
        self._temperature = temperature
        self._to = to
        self._max_retries = max_retries

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Анализирует задачу + UI-контекст через LLM, записывает action."""
        llm_client = self._get_llm_client(context)
        if llm_client is None:
            exchange.fail(
                "ai_rpa: LLM client не доступен (проверьте настройки AI провайдера)"
            )
            return

        prompt = self._build_prompt(exchange)
        last_error: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                response = await llm_client.chat(
                    model=self._model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self._temperature,
                )
                action = self._parse_llm_response(response)
                exchange.set_property(self._action_property, action)
                self._write(exchange, action)
                return
            except Exception as exc:
                last_error = exc
                _logger.warning(
                    "ai_rpa attempt %s/%s failed: %s", attempt, self._max_retries, exc
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(
                        0.5 * (2 ** (attempt - 1))
                    )  # exponential backoff

        exchange.fail(
            f"ai_rpa: LLM call failed after {self._max_retries} attempts: {last_error}"
        )

    def _get_llm_client(self, context: ExecutionContext):
        """Извлекает LLM client из контекста выполнения."""
        client = getattr(context, "llm_client", None)
        if client is not None:
            return client

        app_state = getattr(context, "app_state", None)
        if app_state is not None:
            client = getattr(app_state, "llm_client", None)
            if client is not None:
                return client
            client = getattr(app_state, "ai_gateway", None)
            if client is not None:
                return client

        return None

    def _build_prompt(self, exchange: Exchange[Any]) -> str:
        """Строит промпт для LLM с задачей и UI-контекстом."""
        context_parts = [f"Задача: {self._task}"]

        for key, value in self._ui_context.items():
            if (
                isinstance(value, str)
                and value.startswith("${")
                and value.endswith("}")
            ):
                prop_path = value[2:-1]
                resolved = self._resolve_property(exchange, prop_path)
                context_parts.append(f"{key}: {resolved}")
            else:
                context_parts.append(f"{key}: {value}")

        context_parts.append(
            "\nДоступные действия: click, type, screenshot, hover, scroll, wait"
        )
        context_parts.append(
            "Верни строго валидный JSON без markdown-форматирования с полями: "
            "action (string), params (object), reasoning (string). "
            'Пример: {"action": "click", "params": {"x": 100, "y": 200}, "reasoning": "..."}'
        )

        return "\n".join(context_parts)

    def _resolve_property(self, exchange: Exchange[Any], path: str) -> str:
        """Разрешает property reference в значение."""
        if path.startswith("property:"):
            key = path[len("property:") :]
            value = exchange.properties.get(key)
            return str(value) if value is not None else ""
        if path.startswith("body."):
            key = path[len("body.") :]
            body = exchange.in_message.body
            if isinstance(body, dict):
                value = body.get(key)
                return str(value) if value is not None else ""
        return ""

    def _parse_llm_response(self, response: Any) -> dict[str, Any]:
        """Парсит LLM response в структурированный action с Pydantic validation."""
        content = ""
        if hasattr(response, "content"):
            content = response.content
        elif isinstance(response, dict):
            content = response.get("content", "")
        elif isinstance(response, str):
            content = response

        # Try to extract JSON from markdown code blocks or raw text
        text = content.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        data: dict[str, Any] | None = None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Fallback: find first JSON object in text
            brace_start = text.find("{")
            brace_end = text.rfind("}")
            if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
                try:
                    data = json.loads(text[brace_start : brace_end + 1])
                except json.JSONDecodeError:
                    pass

        if data is None:
            raise ValueError(f"No valid JSON found in LLM response: {content!r}")

        # Validate via Pydantic schema
        try:
            validated = RPAAction.model_validate(data)
        except ValidationError as exc:
            raise ValueError(
                f"LLM response does not match RPAAction schema: {exc}"
            ) from exc

        # Validate action against allowed set (defense in depth)
        if validated.action not in _VALID_ACTIONS:
            raise ValueError(
                f"Invalid action '{validated.action}'; expected one of {_VALID_ACTIONS}"
            )

        return validated.model_dump()

    def _write(self, exchange: Exchange[Any], value: Any) -> None:
        """Записывает результат в указанный target."""
        target = self._to
        if target.startswith("property:"):
            exchange.set_property(target[len("property:") :], value)
            return
        if target == "body":
            exchange.in_message.body = value
            return
        if target.startswith("body."):
            key = target[len("body.") :]
            body = exchange.in_message.body
            if not isinstance(body, dict):
                body = {}
            body[key] = value
            exchange.in_message.body = body
            return
        exchange.set_property(target, value)

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {"task": self._task}
        if self._ui_context:
            spec["ui_context"] = self._ui_context
        if self._action_property != "ai_rpa.action":
            spec["action_property"] = self._action_property
        if self._model != "gpt-4o":
            spec["model"] = self._model
        if self._temperature != 0.1:
            spec["temperature"] = self._temperature
        return {"ai_rpa": spec}
