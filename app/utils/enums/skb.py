import enum


__all__ = ("ResponseTypeChoices",)


class ResponseTypeChoices(enum.Enum):
    """
    Перечисление для выбора типа ответа.

    Используется для указания формата, в котором должен быть возвращен ответ.

    Значения:
        json (str): Ответ в формате JSON.
        pdf (str): Ответ в формате PDF.
    """

    json = "JSON"
    pdf = "PDF"
