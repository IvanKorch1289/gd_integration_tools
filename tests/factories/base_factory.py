"""
Базовая фабрика тестовых данных.

Предоставляет общий интерфейс для генерации фейковых объектов
в unit и integration тестах. Не зависит от БД или внешних сервисов.

Пример использования::

    class OrderFactory(BaseFactory):
        model = OrderSchema

        @classmethod
        def defaults(cls) -> dict:
            return {"id": "test-1", "amount": 100, "status": "pending"}

    order = OrderFactory.build(amount=200)
"""

from __future__ import annotations

from typing import Any, ClassVar


class BaseFactory:
    """Базовая фабрика для создания тестовых объектов.

    Наследники переопределяют ``model`` и ``defaults``.

    Атрибуты:
        model: Pydantic-схема или dataclass для создания объекта.
    """

    model: ClassVar[type | None] = None

    @classmethod
    def defaults(cls) -> dict[str, Any]:
        """Возвращает словарь значений по умолчанию.

        Returns:
            Словарь field → default_value.
        """
        return {}

    @classmethod
    def build(cls, **overrides: Any) -> Any:
        """Создаёт экземпляр модели с опциональными переопределениями.

        Args:
            overrides: Поля для переопределения поверх defaults().

        Returns:
            Экземпляр модели или словарь если model не задана.

        Raises:
            TypeError: Если model задана, но не поддерживает **kwargs.
        """
        data = {**cls.defaults(), **overrides}
        if cls.model is not None:
            return cls.model(**data)
        return data

    @classmethod
    def build_many(cls, count: int, **overrides: Any) -> list[Any]:
        """Создаёт несколько экземпляров.

        Args:
            count: Количество объектов.
            overrides: Общие поля для переопределения.

        Returns:
            Список экземпляров модели.
        """
        return [cls.build(**overrides) for _ in range(count)]
