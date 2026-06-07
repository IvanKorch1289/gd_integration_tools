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
from src.backend.infrastructure.logging.factory import get_logger


from typing import TYPE_CHECKING, Any

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("AIRpaProcessor",)

_logger = get_logger(__name__)

_VALID_ACTIONS = frozenset({"click", "type", "screenshot", "hover", "scroll", "wait"})


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
    ) -> None:
        super().__init__(name=name or self.name)
        self._task = task
        self._ui_context = dict(ui_context or {})
        self._action_property = action_property
        self._model = model
        self._temperature = temperature
        self._to = to

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Анализирует задачу + UI-контекст через LLM, записывает action."""
        # Получаем LLM client из контекста
        llm_client = self._get_llm_client(context)
        if llm_client is None:
            exchange.fail(
                "ai_rpa: LLM client не доступен (проверьте настройки AI провайдера)"
            )
            return

        # Формируем промпт с задачей и UI-контекстом
        prompt = self._build_prompt(exchange)

        try:
            response = await llm_client.chat(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self._temperature,
            )
            action = self._parse_llm_response(response)
        except Exception as exc:
            exchange.fail(f"ai_rpa: LLM call failed: {exc}")
            return

        # Записываем action в exchange properties
        exchange.set_property(self._action_property, action)
        self._write(exchange, action)

    def _get_llm_client(self, context: ExecutionContext):
        """Извлекает LLM client из контекста выполнения."""
        # Сначала пробуем direct attribute
        client = getattr(context, "llm_client", None)
        if client is not None:
            return client

        # Пробуем через app_state
        app_state = getattr(context, "app_state", None)
        if app_state is not None:
            client = getattr(app_state, "llm_client", None)
            if client is not None:
                return client
            # Пробуем ai_gateway
            client = getattr(app_state, "ai_gateway", None)
            if client is not None:
                return client

        return None

    def _build_prompt(self, exchange: Exchange[Any]) -> str:
        """Строит промпт для LLM с задачей и UI-контекстом."""
        context_parts = [f"Задача: {self._task}"]

        for key, value in self._ui_context.items():
            # Поддержка property reference через ${...}
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
            'Верни JSON: {"action": "...", "params": {...}, "reasoning": "..."}'
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
        """Парсит LLM response в структурированный action."""
        content = ""
        if hasattr(response, "content"):
            content = response.content
        elif isinstance(response, dict):
            content = response.get("content", "")
        elif isinstance(response, str):
            content = response

        # Пытаемся извлечь JSON из ответа
        import json

        try:
            # Прямой JSON
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # Пытаемся найти JSON в тексте
        import re

        json_match = re.search(r"\{[^{}]*\}", content, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        # Fallback: возвращаем сырой response
        return {
            "action": "unknown",
            "params": {},
            "reasoning": content,
            "raw_response": content,
        }

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
