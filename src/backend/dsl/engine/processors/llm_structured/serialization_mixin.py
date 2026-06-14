from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from typing import TYPE_CHECKING

from src.backend.core.logging import get_logger
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.exchange import Exchange

_logger = get_logger(__name__)

# Дефолтный ``temperature`` для structured-output: детерминизм важнее
# креативности при заполнении схемы.
_DEFAULT_TEMPERATURE: float = 0.0
# Максимальное число instructor-retries (внутренний цикл валидации Pydantic).
_DEFAULT_RETRY: int = 3


class SerializationMixin:
    """write_result + to_spec для LLMStructuredProcessor. S65 W2 extraction."""

    __slots__ = ()

    def _write_result(self, exchange: Exchange[Any], result: Any) -> None:
        """Записывает результат в путь ``self._to``.

        Поддерживается:
            * ``body.<field>`` — обновляет body (создаёт dict если нужен);
            * ``body`` — заменяет body целиком;
            * ``property:<name>`` — пишет в ``exchange.properties[name]``.

        Args:
            exchange: Текущий exchange.
            result: Pydantic-объект (валидный по схеме).
        """
        target = self._to
        if target.startswith("property:"):
            key = target[len("property:") :]
            exchange.set_property(key, result)
            return
        if target == "body":
            exchange.in_message.body = result
            return
        if target.startswith("body."):
            key = target[len("body.") :]
            body = exchange.in_message.body
            if not isinstance(body, dict):
                body = {}
            body[key] = result
            exchange.in_message.body = body
            return

        # Fallback: трактуем как property name.
        exchange.set_property(target, result)

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализует процессор в YAML-spec для round-trip."""
        spec: dict[str, Any] = {
            "model": self._model,
            "prompt": self._prompt_template,
            "retry": self._retry,
            "to": self._to,
        }
        if self._temperature != _DEFAULT_TEMPERATURE:
            spec["temperature"] = self._temperature
        if self._cost_budget_usd is not None:
            spec["cost_budget_usd"] = self._cost_budget_usd
        # output_schema → строка
        ref = self._output_schema_ref
        if isinstance(ref, str):
            spec["output_schema"] = ref
        elif ref is not None:
            spec["output_schema"] = f"{ref.__module__}:{ref.__name__}"
        return {"llm_structured": spec}
