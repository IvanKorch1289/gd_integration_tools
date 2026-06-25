"""Streamlit entry point (main page).

S171: thin wrapper — перенаправляет на ``00_Главная``.
Реальный dashboard (метрики + health + навигация) находится в
``pages/00_Главная.py``. Это сделано для того, чтобы Streamlit
показывал sidebar navigation.

NOTE: запускать через ``python manage.py run-frontend``.
"""

from __future__ import annotations

from pathlib import Path

_project_root = Path(__file__).resolve().parents[3]

# Заголовок страницы (показывается в browser tab + sidebar).
import streamlit as st

st.set_page_config(
    page_title="GD Integration Tools",
    page_icon=":bank:",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Рендерим содержимое главной страницы через Page API.
# Используем switch_page чтобы сразу попасть на 00_Главная.
st.switch_page("pages/00_Главная.py")