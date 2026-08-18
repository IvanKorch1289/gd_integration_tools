"""Pure value converters (extracted from dsl/codec/converters.py in Sprint 224).

Чистые функции без DSL-логики — перенесены в core/utils/ для устранения
3 layer-violation (services/tech.py, entrypoints/middlewares/admin_ip.py,
entrypoints/middlewares/api_key.py импортировали эти утилиты из
dsl/codec/, что нарушает layer policy: core/utils/ — канонический
домен для utility функций).

Public API preserved 1:1 (signature, behavior). Dsl shim остаётся
as back-compat re-export (deprecation cycle s24).

Used by:
- services/core/tech.py (after Sprint 224 migration)
- entrypoints/middlewares/admin_ip.py (after Sprint 224 migration)
- entrypoints/middlewares/api_key.py (after Sprint 224 migration)
- dsl/codec/converters.py (back-compat re-export)
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from src.backend.core.logging import get_logger

__all__ = ("convert_numpy_types", "convert_pattern", "transfer_model_to_schema")


def convert_numpy_types(value: Any) -> Any:
    """numpy/Arrow скаляр → нативный Python тип.

    Обрабатывает: bool, int, float, objects с .item() методом (numpy
    scalars). Возвращает value as-is если не удаётся конвертировать.
    """
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return item()
        except Exception as _:
            return value
    return value


def convert_pattern(pattern: str) -> str:
    """Glob-подобный pattern → regex (``*`` → ``.*``, якоря по краям).

    Special case: pattern == "/" → "^/$" (root path).
    """
    started_symbol = "^" if pattern == "/" else "^.*"
    return f"{started_symbol}{pattern.replace('*', '.*')}$"


def transfer_model_to_schema(
    instance: Any, schema: type[BaseModel], from_attributes: bool = False,
) -> BaseModel:
    """ORM/dict → pydantic-схема через ``model_validate``.

    На errors → log + raise ValueError (НЕ raise original exception —
    канонический contract для caller'ов).
    """
    logger = get_logger(__name__)
    try:
        return schema.model_validate(instance, from_attributes=from_attributes)
    except Exception as exc:
        logger.error(
            "Ошибка преобразования модели в схему: %s", str(exc), exc_info=True,
        )
        raise ValueError("Ошибка преобразования модели в схему") from exc
