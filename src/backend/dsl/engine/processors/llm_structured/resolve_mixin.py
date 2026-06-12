from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from typing import TYPE_CHECKING

from src.backend.core.logging import get_logger
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from pydantic import BaseModel

    from src.backend.dsl.engine.exchange import Exchange

_logger = get_logger(__name__)

# Дефолтный ``temperature`` для structured-output: детерминизм важнее
# креативности при заполнении схемы.
_DEFAULT_TEMPERATURE: float = 0.0
# Максимальное число instructor-retries (внутренний цикл валидации Pydantic).
_DEFAULT_RETRY: int = 3


@processor(
    "llm_structured",
    namespace="core",
    spec_schema={
        "type": "object",
        "required": ["model", "output_schema", "prompt"],
        "properties": {
            "model": {"type": "string"},
            "output_schema": {"type": ["string", "object", "null"]},
            "prompt": {"type": "string"},
            "retry": {"type": "integer", "minimum": 0, "default": _DEFAULT_RETRY},
            "temperature": {
                "type": "number",
                "minimum": 0.0,
                "default": _DEFAULT_TEMPERATURE,
            },
            "cost_budget_usd": {"type": ["number", "null"]},
            "to": {"type": "string"},
        },
    },
    capabilities=("ai.llm.litellm", "net.outbound.litellm:external"),
    meta={"tier": 2, "category": "ai", "version": "v17"},
    tags=("ai", "llm", "structured-output"),
)
class ResolveMixin:
    """resolve schema + prompt + provider для LLMStructuredProcessor. S65 W2 extraction."""

    __slots__ = ()

    def _resolve_schema(self) -> type[BaseModel]:
        """Резолвит ``output_schema`` в Pydantic-класс.

        Поддерживается:
            * Прямой ``type[BaseModel]`` — возвращается как есть;
            * Строка ``module:ClassName`` — динамический import;
            * Имя ``ClassName`` — поиск в
              :class:`ServiceSchemaRegistry` (kind=processor) с
              fallback на ``importlib.import_module`` если в meta
              записан ``module``.

        Raises:
            ValueError: Не удалось резолвить схему.
        """
        from pydantic import BaseModel

        ref = self._output_schema_ref
        if ref is None:
            raise ValueError("llm_structured: output_schema обязателен")
        if isinstance(ref, type) and issubclass(ref, BaseModel):
            return ref
        if not isinstance(ref, str):
            raise ValueError(
                f"llm_structured: output_schema должен быть Pydantic-классом "
                f"или строкой 'module:Class', получено {type(ref).__name__}"
            )

        # 1) Полный путь module:Class — динамический import.
        if ":" in ref:
            import importlib

            module_name, _, class_name = ref.partition(":")
            module = importlib.import_module(module_name)
            cls = getattr(module, class_name, None)
            if cls is None or not (
                isinstance(cls, type) and issubclass(cls, BaseModel)
            ):
                raise ValueError(
                    f"llm_structured: {ref!r} не указывает на Pydantic-класс"
                )
            return cls

        # 2) Имя класса — поиск в ServiceSchemaRegistry meta.
        try:
            from src.backend.services.schema_registry import (
                SchemaKind,
                get_schema_registry,
            )

            entry = get_schema_registry().get(SchemaKind.PROCESSOR, ref)
        except (ImportError, AttributeError):
            entry = None

        if entry is not None:
            module_name = entry.meta.get("module")
            if module_name:
                import importlib

                module = importlib.import_module(module_name)
                cls = getattr(module, ref, None)
                if (
                    cls is not None
                    and isinstance(cls, type)
                    and issubclass(cls, BaseModel)
                ):
                    return cls

        raise ValueError(
            f"llm_structured: не удалось резолвить output_schema={ref!r}; "
            "используйте 'module:ClassName' или зарегистрируйте схему в "
            "ServiceSchemaRegistry с meta['module']"
        )

    def _resolve_prompt(self, exchange: Exchange[Any]) -> str:
        """Подставляет ``${body.x}`` / ``${properties.y}`` из exchange.

        Args:
            exchange: Текущий exchange.

        Returns:
            Готовый prompt-string.
        """
        body = exchange.in_message.body
        body_dict = body if isinstance(body, dict) else {"_raw": body}

        # Простой шаблонизатор ${path}: KISS вместо Jinja2 (тяжёлая deps).
        # Поддержка: ${body.field}, ${properties.key}, ${body} (raw).
        import re

        pattern = re.compile(r"\$\{([^}]+)\}")

        def _replace(match: re.Match[str]) -> str:
            path = match.group(1).strip()
            if path == "body":
                return str(body)
            if path.startswith("body."):
                key = path[len("body.") :]
                return str(body_dict.get(key, ""))
            if path.startswith("properties."):
                key = path[len("properties.") :]
                return str(exchange.properties.get(key, ""))
            # Неизвестный префикс — оставляем placeholder как-есть для отладки.
            return match.group(0)

        return pattern.sub(_replace, self._prompt_template)

    def _provider_name(self) -> str:
        """Извлекает имя провайдера из ``model`` для capability/трейсов."""
        return self._model.split("/", 1)[0]
