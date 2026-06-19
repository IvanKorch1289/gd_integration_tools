"""Workflow TypedDict definitions (S168 W12 P2-7 partial).

S168 W12 P2-7: moved from src/backend/workflows/dicts.py per master
prompt v8 P2-7: "Delete src/backend/workflows/; merge into
infrastructure/workflow/{runner,outbox,registry}/".

ProcessingResult is a TypedDict — fits better in schemas/ than workflow
runner (it's a data shape, not a runner concept).
"""

from typing import Any, TypedDict

__all__ = ("ProcessingResult",)


class ProcessingResult(TypedDict):
    """
    Типизированный словарь для представления результатов обработки заказа.

    Атрибуты:
        success (bool): Флаг успешности выполнения операции.
        order_id (str): Уникальный идентификатор заказа.
        result_data (Dict): Словарь с дополнительными данными результата.
        error_message (str | None): Сообщение об ошибке (при наличии).
    """

    success: bool
    order_id: str
    result_data: dict[str, Any]
    error_message: str | None
