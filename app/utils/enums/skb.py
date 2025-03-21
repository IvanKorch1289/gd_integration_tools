from enum import Enum


__all__ = ("ResponseTypeChoices",)


class ResponseTypeChoices(Enum):
    """
    Перечисление для выбора типа ответа.

    Используется для указания формата, в котором должен быть возвращен ответ.

    Значения:
        json (str): Ответ в формате JSON.
        pdf (str): Ответ в формате PDF.
    """

    json = "JSON"
    pdf = "PDF"
