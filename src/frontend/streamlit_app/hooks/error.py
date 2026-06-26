"""Error-handling хуки для Streamlit страниц."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import streamlit as st


class StreamlitError(Exception):
    """Базовый класс ошибок для Streamlit-страниц."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class APIError(StreamlitError):
    """Ошибка при вызове API."""


class ValidationError(StreamlitError):
    """Ошибка валидации данных."""


def handle_api_error(
    exc: Exception,
    *,
    default_message: str = "Произошла ошибка при обращении к API",
    show_details: bool = False,
) -> None:
    """Обработать ошибку API и показать сообщение в UI.

    Args:
        exc: Перехваченное исключение.
        default_message: Сообщение по умолчанию.
        show_details: Показывать ли детали ошибки.
    """
    if isinstance(exc, PermissionError):
        st.error("⛔ Недостаточно прав для выполнения операции")
    elif isinstance(exc, APIError):
        st.error(f"❌ API Error: {exc.message}")
        if show_details and exc.details:
            with st.expander("Подробности"):
                st.json(exc.details)
    elif isinstance(exc, ValidationError):
        st.warning(f"⚠️ {exc.message}")
    elif "connection" in str(exc).lower():
        st.error("🔌 Нет соединения с сервером")
    elif "timeout" in str(exc).lower():
        st.error("⏱️ Превышен таймаут ожидания")
    else:
        st.error(f"❌ {default_message}")
        if show_details:
            with st.expander("Technical details"):
                st.text(str(exc))


def try_except(
    default: Any = None, *, message: str = "Произошла ошибка", reraise: bool = False
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Декоратор для обработки исключений в функциях страниц.

    Args:
        default: Значение по умолчанию при ошибке.
        message: Сообщение при ошибке.
        reraise: Перевыбросить исключение после логирования.

    Returns:
        Декорированная функция.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                handle_api_error(exc, default_message=message)
                if reraise:
                    raise
                return default

        return wrapper

    return decorator


def require_api_client(func: Callable[..., Any]) -> Callable[..., Any]:
    """Декоратор проверки доступности API-клиента.

    Args:
        func: Декорируемая функция.

    Returns:
        Декорированная функция.
    """

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        from src.frontend.streamlit_app.api_clients.base import get_base_client

        try:
            client = get_base_client()
            # Простой health check
            client.get("/api/v1/health/components")
            return func(*args, **kwargs)
        except Exception as exc:
            handle_api_error(exc, default_message="API недоступен")
            return None

    return wrapper
