"""DSL processor ``validate_response`` (R-V15-18 — Step 7).

Pydantic-валидация ``response_body`` (по умолчанию — ``out_message.body``
последнего processor'а) с тремя стратегиями ``on_error``:

    * ``"fail"`` — останавливает pipeline через ``exchange.fail(...)``;
    * ``"dlq"`` — помечает exchange ``_dlq=True`` + ставит в свойство
      ``_validation_error`` детали (опциональное использование downstream
      DLQ-консьюмером);
    * ``"warn"`` — пишет warning-лог и проставляет
      ``response_validation_status=warn`` в properties без остановки.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor
from src.backend.infrastructure.logging.factory import get_logger

if TYPE_CHECKING:
    from pydantic import BaseModel

    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


__all__ = ("ResponseValidatorProcessor",)


_ALLOWED_ON_ERROR = frozenset({"fail", "dlq", "warn"})
_logger = get_logger(__name__)


@processor(
    "validate_response",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "schema": {"type": ["string", "null"]},
            "on_error": {"type": "string", "enum": sorted(_ALLOWED_ON_ERROR)},
            "source": {"type": "string"},
        },
    },
    meta={"tier": 1, "category": "validation"},
)
class ResponseValidatorProcessor(BaseProcessor):
    """Валидирует response_body против Pydantic-модели.

    Args:
        schema: Класс Pydantic-модели (если передаётся через builder) или
            строка ``module:ClassName`` для YAML-loader. Если ``None`` —
            процессор no-op (используется как шаблон в YAML до подстановки).
        on_error: ``fail`` | ``dlq`` | ``warn``.
        source: Откуда брать тело: ``out_body`` (default — ``out_message.body``
            если есть, иначе ``in_message.body``) или ``in_body``.
    """

    def __init__(
        self,
        *,
        schema: type[BaseModel] | str | None = None,
        on_error: str = "fail",
        source: str = "out_body",
    ) -> None:
        super().__init__(name="validate_response")
        if on_error not in _ALLOWED_ON_ERROR:
            allowed = ", ".join(sorted(_ALLOWED_ON_ERROR))
            raise ValueError(
                f"validate_response: on_error must be one of {allowed}, "
                f"got {on_error!r}"
            )
        self.schema = schema
        self.on_error = on_error
        self.source = source

    def _resolve_schema(self) -> type[BaseModel] | None:
        """Поддержка string-ref ``module:ClassName`` для YAML-loader."""
        if self.schema is None:
            return None
        if isinstance(self.schema, str):
            import importlib

            module_name, _, class_name = self.schema.partition(":")
            if not module_name or not class_name:
                raise ValueError(
                    f"validate_response schema string must be 'module:Class', "
                    f"got {self.schema!r}"
                )
            module = importlib.import_module(module_name)
            return getattr(module, class_name)
        return self.schema

    def _resolve_body(self, exchange: Exchange[Any]) -> Any:
        if self.source == "in_body":
            return exchange.in_message.body
        out_message = getattr(exchange, "out_message", None)
        if out_message is not None:
            body = getattr(out_message, "body", None)
            if body is not None:
                return body
        return exchange.in_message.body

    def _handle_error(self, exchange: Exchange[Any], error: Exception) -> None:
        message = f"validate_response failed: {error}"
        match self.on_error:
            case "fail":
                exchange.fail(message)
            case "dlq":
                exchange.set_property("_dlq", True)
                exchange.set_property("_validation_error", str(error))
                _logger.warning("validate_response → DLQ: %s", message)
            case "warn":
                exchange.set_property("response_validation_status", "warn")
                exchange.set_property("_validation_error", str(error))
                _logger.warning("validate_response (warn): %s", message)

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        model = self._resolve_schema()
        if model is None:
            return  # no-op до подстановки реальной модели

        body = self._resolve_body(exchange)
        try:
            validated = model.model_validate(body)
        except Exception as exc:  # pydantic.ValidationError + прочее
            self._handle_error(exchange, exc)
            return

        exchange.set_property("response_validation_status", "ok")
        exchange.set_property("_validated_body", validated)

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {"on_error": self.on_error}
        if isinstance(self.schema, str):
            spec["schema"] = self.schema
        elif self.schema is not None:
            spec["schema"] = f"{self.schema.__module__}:{self.schema.__name__}"
        if self.source != "out_body":
            spec["source"] = self.source
        return {"validate_response": spec}
