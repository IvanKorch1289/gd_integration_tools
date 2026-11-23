"""Перечисления интеграции СКБ-Техно и нормализация типа ответа."""

from enum import Enum
from typing import Any

__all__ = ("ResponseTypeChoices", "response_type_value")


class ResponseTypeChoices(Enum):
    """Перечисление для выбора типа ответа.

    Используется для указания формата, в котором должен быть возвращен ответ.

    Значения:
        json: Ответ в формате JSON (значение ``"JSON"``).
        pdf: Ответ в формате PDF (значение ``"PDF"``).
    """

    json = "JSON"
    pdf = "PDF"


def response_type_value(response_type: Any) -> str | None:
    """Привести значение типа ответа к строке (``"JSON"`` / ``"PDF"``).

    Тип ответа приходит из разных слоёв и в разных формах:

    * enum-член :class:`ResponseTypeChoices` — query-параметр FastAPI
      разбирается в enum ДО вызова сервиса;
    * строка (``"PDF"``) — JSON/DSL-контракты;
    * объект с атрибутом ``value`` (например, значение из другого пакета).

    Сравнение enum-члена со строкой даёт ``False``, из-за чего ветка «PDF»
    не срабатывала: клиент, запросивший документ, получал JSON. Здесь
    значение приводится к строке единообразно.

    Args:
        response_type: Значение типа ответа (любой из перечисленных видов).

    Returns:
        ``"JSON"`` / ``"PDF"`` либо ``None``, если значение не распознано.
    """
    if response_type is None:
        return None
    value = getattr(response_type, "value", response_type)
    if not isinstance(value, str):
        return None
    return value.upper()
