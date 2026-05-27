"""Form-компоненты для ввода данных."""

from __future__ import annotations

from typing import Any, Callable

import streamlit as st


def text_input(
    label: str,
    value: str = "",
    *,
    placeholder: str | None = None,
    help: str | None = None,
    key: str | None = None,
) -> str:
    """Текстовое поле ввода.

    Args:
        label: Название поля.
        value: Начальное значение.
        placeholder: Placeholder текст.
        help: Текст подсказки.
        key: Уникальный ключ виджета.

    Returns:
        Введённое значение.
    """
    return st.text_input(
        label,
        value=value,
        placeholder=placeholder,
        help=help,
        key=key,
    )


def number_input(
    label: str,
    value: float = 0,
    *,
    min_value: float | None = None,
    max_value: float | None = None,
    step: float | None = None,
    help: str | None = None,
    key: str | None = None,
) -> float:
    """Поле для ввода числа.

    Args:
        label: Название поля.
        value: Начальное значение.
        min_value: Минимум.
        max_value: Максимум.
        step: Шаг.
        help: Текст подсказки.
        key: Уникальный ключ виджета.

    Returns:
        Введённое значение.
    """
    return st.number_input(
        label,
        value=value,
        min_value=min_value,
        max_value=max_value,
        step=step,
        help=help,
        key=key,
    )


def select_input(
    label: str,
    options: list[str],
    *,
    index: int = 0,
    help: str | None = None,
    key: str | None = None,
) -> str:
    """Select-бокс.

    Args:
        label: Название поля.
        options: Список опций.
        index: Индекс выбранной опции по умолчанию.
        help: Текст подсказки.
        key: Уникальный ключ виджета.

    Returns:
        Выбранная опция.
    """
    return st.selectbox(
        label,
        options=options,
        index=index,
        help=help,
        key=key,
    )


def multiselect_input(
    label: str,
    options: list[str],
    *,
    default: list[str] | None = None,
    help: str | None = None,
    key: str | None = None,
) -> list[str]:
    """Мультиселект.

    Args:
        label: Название поля.
        options: Список опций.
        default: Опции по умолчанию.
        help: Текст подсказки.
        key: Уникальный ключ виджета.

    Returns:
        Список выбранных опций.
    """
    return st.multiselect(
        label,
        options=options,
        default=default,
        help=help,
        key=key,
    )


def date_input(
    label: str,
    value: Any = None,
    *,
    help: str | None = None,
    key: str | None = None,
) -> Any:
    """Поле для ввода даты.

    Args:
        label: Название поля.
        value: Начальная дата.
        help: Текст подсказки.
        key: Уникальный ключ виджета.

    Returns:
        Выбранная дата.
    """
    return st.date_input(
        label,
        value=value,
        help=help,
        key=key,
    )


def form_submit(
    label: str = "Submit",
    *,
    disabled: bool = False,
    help: str | None = None,
) -> bool:
    """Кнопка submit для формы.

    Args:
        label: Текст кнопки.
        disabled: Заблокирована ли кнопка.
        help: Текст подсказки.

    Returns:
        True если форма отправлена.
    """
    return st.form_submit_button(
        label,
        disabled=disabled,
        help=help,
    )


def on_submit_callback(callback: Callable[[], None]) -> None:
    """Регистрация callback-а на submit формы.

    Args:
        callback: Функция-обработчик.
    """
    # Streamlit формы используют st.form_submit_button
    # Callback логика реализуется через session_state
    pass
