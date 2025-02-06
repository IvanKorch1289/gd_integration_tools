import enum


__all__ = ("OrderingTypeChoices",)


class OrderingTypeChoices(enum.Enum):
    """
    Перечисление для выбора типа cортировки объектов.

    Используется для указания формата, в котором должен быть возвращен ответ.

    Значения:
        asc (str): По возрастанию.
        desc (str): По убыванию.
    """

    ascending = "asc"
    descending = "desc"
