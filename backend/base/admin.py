from typing import List


__all__ = ("BaseAdmin",)


class BaseAdmin:
    """
    Базовый класс для административных панелей.

    Атрибуты:
        page_size (int): Количество элементов на странице по умолчанию.
        page_size_options (List[int]): Список доступных вариантов количества элементов на странице.
    """

    page_size: int = 20
    page_size_options: List[int] = [25, 50, 100, 200]
