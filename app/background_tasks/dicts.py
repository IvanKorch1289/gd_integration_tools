from typing import Any, Dict, TypedDict


__all__ = ("ProcessingResult",)


class ProcessingResult(TypedDict):
    """
    Типизированный словарь для представления результатов обработки заказа.

    Атрибуты:
        success (bool): Флаг успешности выполнения операции.
        order_id (str): Уникальный идентификатор заказа.
        result_data (Dict): Словарь с дополнительными данными результата.
        error_message (str | None): Сообщение об ошибке (при наличии).

    Пример использования:
        >>> result: ProcessingResult = {
        ...     "success": True,
        ...     "order_id": "12345",
        ...     "result_data": {"status": "completed"},
        ...     "error_message": None
        ... }
    """

    success: bool
    order_id: str
    result_data: Dict[str, Any] | None
    error_message: str | None
