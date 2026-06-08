"""Undo/redo history для DSL Visual Editor (S77 W3 split).

Извлечено из ``31_DSL_Visual_Editor.py``. Pure-функции, зависят
от ``st.session_state`` (lazy import — модуль можно импортировать
без ``[frontend]`` extra).

API backward-compatible со старыми private именами
(``_push_history``, ``_can_undo``, ``_can_redo``, ``_undo``, ``_redo``).
Здесь экспортируются как public без underscore (для unit-тестов и
re-use из main page).

Wave: ``[wave:s77/w3-dsl-editor-split]``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import streamlit as st

__all__ = (
    "can_redo",
    "can_undo",
    "init_history",
    "push_history",
    "redo",
    "undo",
)

# Максимальный размер undo-стека.
_MAX_HISTORY: int = 50


def _require_streamlit() -> "st":  # type: ignore[type-arg]
    """Lazy import streamlit (module-level импорт ломает тесты без [frontend])."""
    import streamlit as st

    return st


def init_history() -> None:
    """Инициализирует ``yaml_history`` стек если ещё не существует.

    Идемпотентна: повторные вызовы — no-op. Вызывать в начале page
    setup ДО первого push_history().
    """
    st = _require_streamlit()
    if "yaml_history" not in st.session_state:
        st.session_state.yaml_history = [st.session_state.yaml]
        st.session_state.yaml_history_index = 0


def push_history() -> None:
    """Push current yaml state to history stack.

    * Truncates forward history если курсор не на вершине стека.
    * Appends current state.
    * Trims to ``_MAX_HISTORY`` (drops oldest).
    * Updates ``yaml_history_index`` на вершину.
    """
    st = _require_streamlit()
    if "yaml_history" not in st.session_state:
        st.session_state.yaml_history = []
    if "yaml_history_index" not in st.session_state:
        st.session_state.yaml_history_index = -1

    # Truncate forward history if we're not at the end.
    if st.session_state.yaml_history_index < len(st.session_state.yaml_history) - 1:
        st.session_state.yaml_history = st.session_state.yaml_history[
            : st.session_state.yaml_history_index + 1
        ]

    # Add current state.
    st.session_state.yaml_history.append(st.session_state.yaml)
    if len(st.session_state.yaml_history) > _MAX_HISTORY:
        st.session_state.yaml_history.pop(0)
    st.session_state.yaml_history_index = len(st.session_state.yaml_history) - 1


def can_undo() -> bool:
    """Есть ли шаг для отмены."""
    st = _require_streamlit()
    return st.session_state.get("yaml_history_index", -1) > 0


def can_redo() -> bool:
    """Есть ли шаг для повтора."""
    st = _require_streamlit()
    hist = st.session_state.get("yaml_history", [])
    idx = st.session_state.get("yaml_history_index", -1)
    return idx >= 0 and idx < len(hist) - 1


def undo() -> None:
    """Откат к предыдущему состоянию (если есть). Вызывает ``st.rerun``."""
    st = _require_streamlit()
    if can_undo():
        st.session_state.yaml_history_index -= 1
        st.session_state.yaml = st.session_state.yaml_history[
            st.session_state.yaml_history_index
        ]
        st.rerun()


def redo() -> None:
    """Возврат к отменённому состоянию (если есть). Вызывает ``st.rerun``."""
    st = _require_streamlit()
    if can_redo():
        st.session_state.yaml_history_index += 1
        st.session_state.yaml = st.session_state.yaml_history[
            st.session_state.yaml_history_index
        ]
        st.rerun()
