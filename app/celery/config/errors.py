from typing import Optional


__all__ = (
    "CeleryHealthError",
    "CeleryConnectionError",
    "QueueUnavailableError",
    "BeatNotRunningError",
)


class CeleryHealthError(Exception):
    """Базовое исключение для ошибок здоровья Celery"""

    def __init__(self, message: str, details: Optional[str] = None):
        self.message = message
        self.details = details
        super().__init__(message)


class CeleryConnectionError(CeleryHealthError):
    """Ошибка соединения с Celery"""


class QueueUnavailableError(CeleryHealthError):
    """Ошибка отсутствия активных очередей"""


class BeatNotRunningError(CeleryHealthError):
    """Ошибка соединения с Celery Beat"""
