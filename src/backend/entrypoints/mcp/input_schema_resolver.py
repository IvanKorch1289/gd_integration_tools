"""Резолвер input_schema для MCP tools на основе ActionSpec reflection.

Назначение:
    K4 Sprint-3 Wave 2 (PLAN.md V17/V18).
    Параметризация input_schema для FastMCP tools через Pydantic reflection:
    для каждого ActionSpec (Tier 1+2) генерирует JSON-Schema из Pydantic
    params model и предоставляет scaffold для регистрации как FastMCP tool.

Принципы:
    - Только новые файлы; существующий mcp_server.py не модифицируется.
    - jsonschema lazy-import (тяжёлая библиотека, нужна только для валидации).
    - strict mode управляется через feature_flags.mcp_tools_input_schema_strict.
    - Интеграция в mcp_server.py — отдельная Wave.

Использование::

    from src.backend.entrypoints.mcp.input_schema_resolver import (
        resolve_input_schema,
        validate_input_schema,
        ResolvedToolSchema,
    )

    schema = resolve_input_schema(action_spec)
    ok, err = validate_input_schema(schema.input_schema, payload)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

__all__ = ("ResolvedToolSchema", "resolve_input_schema", "validate_input_schema")

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ResolvedToolSchema:
    """Разрешённая схема MCP tool для регистрации в FastMCP.

    Attributes:
        name: Имя tool (action_name с заменой точек на подчёркивание).
        description: Описание из ActionSpec или метаданных action.
        input_schema: JSON-Schema payload (из Pydantic model_json_schema).
            Пустой dict ``{}`` если у action нет Pydantic params model.
        output_schema: JSON-Schema ответа (из Pydantic response model).
            Пустой dict ``{}`` если у action нет response model.
    """

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)


def _extract_json_schema(model: type[Any] | None) -> dict[str, Any]:
    """Извлечь JSON-Schema из Pydantic-модели через .model_json_schema().

    Args:
        model: Pydantic BaseModel subclass или None.

    Returns:
        JSON-Schema dict или пустой dict если модель не задана / не Pydantic.
    """
    if model is None:
        return {}
    schema_fn = getattr(model, "model_json_schema", None)
    if not callable(schema_fn):
        # Не Pydantic-модель — возвращаем пустую схему
        logger.debug("Модель %r не имеет .model_json_schema(), schema пропущена", model)
        return {}
    try:
        return schema_fn()  # type: ignore[no-any-return]
    except Exception:  # noqa: BLE001
        logger.warning(
            "Не удалось сгенерировать JSON-Schema для %r", model, exc_info=True
        )
        return {}


def resolve_input_schema(action_spec: Any) -> ResolvedToolSchema:
    """Разрешить input_schema для ActionSpec через Pydantic reflection.

    Читает поля ActionSpec через duck-typing (getattr с дефолтами),
    сохраняя совместимость с layering-политикой проекта (entrypoints
    не зависит от core/ по типам).

    Приоритет выбора input model::

        body_model > path_model > query_model > input_model

    Для ActionMetadata (getattr input_model напрямую).

    Args:
        action_spec: Объект ActionSpec или ActionMetadata. Обязательное
            поле — ``name`` (строка). Все остальные читаются через
            ``getattr`` с дефолтами — нет строгой зависимости от типа.

    Returns:
        :class:`ResolvedToolSchema` с заполненными полями.

    Raises:
        AttributeError: Если ``action_spec`` не имеет поля ``name``.
    """
    # Имя action: action_id > name (аналогично spec_to_metadata.py)
    action_name: str = getattr(action_spec, "action_id", None) or action_spec.name

    # Tool name: точки → подчёркивания (FastMCP-конвенция)
    tool_name = action_name.replace(".", "_")

    description = getattr(action_spec, "description", None) or (
        f"Выполняет action '{action_name}' через интеграционную шину."
    )

    # input_model: body_model > path_model > query_model > input_model
    input_model = (
        getattr(action_spec, "body_model", None)
        or getattr(action_spec, "path_model", None)
        or getattr(action_spec, "query_model", None)
        or getattr(action_spec, "input_model", None)
    )

    # output_model: response_model > output_model
    output_model = getattr(action_spec, "response_model", None) or getattr(
        action_spec, "output_model", None
    )

    input_schema = _extract_json_schema(input_model)
    output_schema = _extract_json_schema(output_model)

    return ResolvedToolSchema(
        name=tool_name,
        description=description,
        input_schema=input_schema,
        output_schema=output_schema,
    )


def validate_input_schema(
    schema: dict[str, Any], payload: dict[str, Any], *, strict: bool | None = None
) -> tuple[bool, str | None]:
    """Валидировать payload против JSON-Schema.

    Lazy-import jsonschema при первом вызове (тяжёлая зависимость).
    Режим strict управляется через feature_flags.mcp_tools_input_schema_strict
    или явным аргументом ``strict``.

    Args:
        schema: JSON-Schema dict (из :func:`resolve_input_schema`).
            Если пустой dict ``{}`` — валидация пропускается (True, None).
        payload: Входные данные для проверки.
        strict: Переопределить глобальный feature_flag. При True
            raise ValidationError вместо возврата (False, msg).
            При None — читает feature_flags.mcp_tools_input_schema_strict.

    Returns:
        Кортеж (ok: bool, error_message: str | None).
        ok=True если валидация прошла или schema пустая.

    Raises:
        jsonschema.ValidationError: Только если strict=True и валидация
            не прошла. В non-strict режиме ошибки возвращаются как (False, msg).
        ImportError: Если jsonschema не установлен (маловероятно — он
            в project deps через openapi-core/fastapi).
    """
    # Пустая схема — пропускаем валидацию
    if not schema:
        return True, None

    # Определяем strict mode: явный аргумент > feature_flag
    if strict is None:
        try:
            from src.backend.core.config.features import feature_flags

            strict = feature_flags.mcp_tools_input_schema_strict
        except Exception:  # noqa: BLE001
            strict = False

    # Lazy-import jsonschema
    try:
        import jsonschema
        from jsonschema import ValidationError as JsonSchemaValidationError
    except ImportError as exc:
        logger.error(
            "jsonschema не установлен — валидация MCP input_schema недоступна: %s", exc
        )
        raise

    try:
        jsonschema.validate(instance=payload, schema=schema)
        return True, None
    except JsonSchemaValidationError as exc:
        error_msg = exc.message
        if strict:
            raise
        logger.debug("MCP input_schema валидация не прошла (non-strict): %s", error_msg)
        return False, error_msg
