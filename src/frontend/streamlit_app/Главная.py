"""Главная страница GD Integration Tools (S172 entry-point).

Это Streamlit entry point (ранее был app.py как redirect).
Содержит dashboard + Quick Access + Search + Metrics + Health.
Запуск: ``python manage.py run-frontend``.

S172 refactor: entry-point filename стал Cyrillic 'Главная.py' чтобы
убрать 'app' label в sidebar (Streamlit использует filename для entry label).
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from src.frontend.streamlit_app.api_clients import (
    cached_get_health,
    cached_get_metrics,
    clear_api_cache,
)
from src.frontend.streamlit_app.shared.auth_state import is_authenticated
from src.frontend.streamlit_app.shared.components import setup_page
from src.frontend.streamlit_app.shared.page_registry import PAGE_METADATA

_project_root = Path(__file__).resolve().parents[3]

setup_page()



# ──────────── S1: Quick Access в sidebar (вверху) ────────────

# Группировка страниц по доменам для улучшения discoverability.
# Каждая группа отображается в sidebar со своим эмодзи + заголовком.
_QUICK_PAGE_GROUPS = [
    ("🎓 Обучение", ["00_Вход", "04_Обучение"]),
    ("🔌 Интеграция", ["11_Маршруты", "37_API_Вызовы", "62_Админ_схем"]),
    ("⚙️ Воркфлоу", ["16_Воркфлоу", "17_Replay_Воркфлоу", "18_Версионирование_Воркфлоу",
                    "19_Saga_Компенсации", "15_Оценка_стоимости_Workflow"]),
    ("🤖 ИИ", ["20_AI_Чат", "22_RAG_Консоль", "23_AI_Учёт_затрат", "47_AI_Безопасность"]),
    ("🛡 Администрирование", ["45_Админ", "50_Фича_флаги", "73_Просмотр_конфига",
                              "70_Тенанты", "72_HITL_Панель"]),
]


def _render_sidebar_search() -> None:
    """Live-фильтр по всем страницам (без submit-кнопки)."""
    st.markdown("### 🔍 Поиск по разделам")
    search = st.text_input(
        "Поиск",
        placeholder="Введите название...",
        label_visibility="collapsed",
        key="sidebar_search",
    )
    if search:
        # Поиск по title + filename (поддержка и кириллицы, и slug)
        q = search.lower()
        matches = [
            (name, meta) for name, meta in PAGE_METADATA.items()
            if q in meta["title"].lower() or q in name.lower()
        ]
        if matches:
            shown = matches[:8]
            extra = len(matches) - len(shown)
            st.markdown(f"**Найдено:** {len(matches)}")
            for name, meta in shown:
                st.page_link(f"pages/{name}.py", label=meta["title"], icon=meta["icon"])
            if extra > 0:
                st.caption(f"…ещё {extra}")
        else:
            st.caption(f"Ничего не найдено по запросу «{search}»")


with st.sidebar:
    _render_sidebar_search()

    st.markdown("### ⚡ Быстрый доступ")
    for group_title, group_pages in _QUICK_PAGE_GROUPS:
        with st.expander(group_title, expanded=True):
            for name in group_pages:
                if name in PAGE_METADATA:
                    meta = PAGE_METADATA[name]
                    st.page_link(
                        f"pages/{name}.py",
                        label=meta["title"],
                        icon=meta["icon"],
                    )

    st.divider()
    st.caption(f"📚 Всего {len(PAGE_METADATA)} страниц в sidebar →")

# ──────────── Header с логотипом ────────────

col_title, col_logo = st.columns([8, 1])
with col_title:
    st.title("GD Integration Tools")
    st.caption("Корпоративная интеграционная шина — Панель управления")
with col_logo:
    logo_path = _project_root / "src" / "static" / "images" / "kuban_credit_logo.svg"
    if logo_path.exists():
        st.image(str(logo_path), width=120)

# ──────────── Если не залогинен — кнопка входа ────────────

if not is_authenticated():
    st.info(
        "Вы не авторизованы. Для доступа к разделам (Заказы, Маршруты, Логи и др.) "
        "необходимо войти."
    )
    if st.button("Войти", type="primary", key="home_login_btn"):
        st.switch_page("pages/00_Вход.py")
    st.divider()

# ──────────── KPI Метрики ────────────

try:
    metrics = cached_get_metrics()
except Exception:
    metrics = {}

if metrics:
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("DSL маршруты", metrics.get("routes_total", 0))
    c2.metric("Действия", metrics.get("actions_count", 0))
    c3.metric("Включено", metrics.get("routes_enabled", 0))
    c4.metric("Отключено (FF)", metrics.get("routes_disabled", 0))
    c5.metric("Сервисы", len(metrics.get("services", [])))
    c6.metric("Фича-флаги", len(metrics.get("feature_flags_disabled", [])))
else:
    st.warning("Не удалось загрузить метрики. Проверьте подключение к backend.")

# ──────────── Component Health ────────────

st.subheader("Здоровье компонентов")

try:
    health = cached_get_health()
except Exception:
    health = {}

if health:
    cols = st.columns(min(len(health), 4))
    for i, (name, status) in enumerate(health.items()):
        with cols[i % len(cols)]:
            if status:
                st.success(f"✓ {name}")
            else:
                st.error(f"✗ {name}")
else:
    st.info("Здоровье компонентов: данные недоступны.")

# ──────────── Auto-refresh ────────────

st.divider()
col_refresh, col_interval = st.columns([1, 3])
with col_refresh:
    if st.button("Обновить", key="home_refresh"):
        clear_api_cache()
        st.rerun()
with col_interval:
    st.caption("Данные обновляются при нажатии «Обновить» или перезагрузке страницы.")

# ──────────── Quick Access (sidebar выше уже показал все разделы) ────────────

st.divider()

st.header("Что внутри")

st.markdown(
    """
**Быстрый старт**

- 👋 Если вы здесь впервые — откройте **🎓 Обучение** в боковой панели (7-шаговый онбординг).
- 🔍 Не знаете, куда идти? Воспользуйтесь **поиском по разделам** выше.
- 📚 Полный список страниц — в боковой панели (sidebar).

**Поддержка**

- Документация по админ-страницам: см. `docs/frontend/`.
- Баги и идеи: внутренний трекер.
"""
)
