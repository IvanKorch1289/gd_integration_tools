"""Конвертеры значений: numpy-скаляры, regex-паттерны, pydantic-модели."""

from typing import Any, Type

from pydantic import BaseModel

from src.infrastructure.external_apis.logging_service import app_logger

__all__ = ("convert_numpy_types", "convert_pattern", "transfer_model_to_schema")


def convert_numpy_types(value: Any) -> Any:
    """numpy/Arrow скаляр → нативный Python тип."""
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
        except Exception:  # noqa: BLE001
            return value
    return value


def convert_pattern(pattern: str) -> str:
    """Glob-подобный pattern → regex (`*` → `.*`, якоря по краям)."""
    started_symbol = "^" if pattern == "/" else "^.*"
    return f"{started_symbol}{pattern.replace('*', '.*')}$"


def transfer_model_to_schema(
    instance: Any, schema: Type[BaseModel], from_attributes: bool = False
) -> BaseModel:
    """ORM/dict → pydantic-схема через `model_validate`."""
    try:
        return schema.model_validate(instance, from_attributes=from_attributes)
    except Exception as exc:
        app_logger.error(
            "Ошибка преобразования модели в схему: %s", str(exc), exc_info=True
        )
        raise ValueError("Ошибка преобразования модели в схему") from exc
