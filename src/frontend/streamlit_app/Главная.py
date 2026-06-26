"""Entry-point + dashboard для GD Integration Tools (S173 router).

S173 refactor: entry-point использует ``st.navigation()`` (Streamlit 1.35+)
для группированного sidebar вместо auto-discovered 69+ плоских ссылок.

Streamlit 1.58 ``st.navigation()`` API:
- dict keys = секции (collapsible в sidebar)
- values = ``st.Page(...)`` (file-based или callable)
- ``position="sidebar"`` — sidebar nav, отключает auto-discovery ``pages/``
- ``expanded=0`` — все секции свёрнуты по умолчанию

Запуск: ``python manage.py run-frontend``.
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


# ──────────── Sections: sidebar группировка по доменам ────────────

_SECTIONS: dict[str, list[str]] = {
    "🎓 Обучение": ["00_Вход", "04_Обучение"],
    "🔌 Интеграция": [
        "10_Заказы", "11_Маршруты", "37_API_Вызовы",
        "57_Файлы_S3", "58_Шина_действий",
        "59_Отладчик_маршрутов", "62_Админ_схем",
    ],
    "⚙️ Воркфлоу": [
        "15_Оценка_стоимости_Workflow", "16_Воркфлоу",
        "17_Replay_Воркфлоу", "18_Версионирование_Воркфлоу",
        "19_Saga_Компенсации", "66_Логи_Воркфлоу",
    ],
    "📊 DSL": [
        "30_DSL_Площадка", "31_DSL_Визуальный_редактор",
        "32_DSL_Конструктор", "33_DSL_Шаблоны",
        "34_DSL_Отладчик", "35_Мастер_генерации_кода",
        "36_Экспресс_боты", "38_Галерея_блюпринтов",
        "39_Консоль_вызовов", "46_DSL_Пробный_прогон",
        "86_Аудит_использования_DSL", "95_Покрытие_EIP",
    ],
    "🤖 AI / RAG": [
        "20_AI_Чат", "21_AI_Обратная_связь",
        "22_RAG_Консоль", "23_AI_Учёт_затрат",
        "47_AI_Безопасность", "48_Лаборатория_промптов",
        "49_Реестр_моделей", "75_Мастер_загрузки_RAG",
        "81_Адаптивная_RAG_панель",
        "85_Массовая_загрузка_RAG",
    ],
    "⏰ Cron": ["13_Конструктор_Cron", "14_Панель_Cron"],
    "🛠 DevOps / Мониторинг": [
        "12_Логи", "41_Поиск", "43_Логи_в_реальном_времени",
        "51_Проверка_здоровья", "52_Устойчивость",
        "53_Монитор_очереди", "54_Replay_DLQ",
        "55_Монитор_пула", "56_Процессы", "60_Админ_кеша",
        "61_Журнал_аудита", "78_Плавная_деградация",
        "79_Редактор_профиля_устойчивости",
        "80_Параллелизм_конвейера",
        "96_Монитор_зависших_сообщений",
    ],
    "🛡 Администрирование": [
        "45_Админ", "50_Фича_флаги", "63_Вики",
        "64_SQL_Админ", "65_Сервисы", "67_Задачи",
        "68_Маркетплейс_плагинов",
        "73_Просмотр_конфига",
        "76_Подключение_плагинов",
        "77_Каталог_процессоров",
    ],
    "🏢 Тенанты": [
        "70_Тенанты", "71_Матрица_возможностей",
        "72_HITL_Панель", "83_Инспекция_тенанта",
        "88_Тенантные_фича_флаги",
    ],
}


# ──────────── Home (dashboard) ────────────

_project_root = Path(__file__).resolve().parents[3]


def _render_home() -> None:
    """Dashboard — выполняется когда выбрана главная страница.

    setup_page() внутри (а не на module level), потому что entry-point
    теперь router и сам контент не рендерит — только выбранная страница.
    """
    setup_page(title="GD Integration Tools", icon=":material/home:")

    # Header
    col_title, col_logo = st.columns([8, 1])
    with col_title:
        st.title("GD Integration Tools")
        st.caption("Корпоративная интеграционная шина — Панель управления")
    with col_logo:
        logo_path = _project_root / "src" / "static" / "images" / "kuban_credit_logo.svg"
        if logo_path.exists():
            st.image(str(logo_path), width=120)

    # Auth gate
    if not is_authenticated():
        st.info(
            "Вы не авторизованы. Для доступа к разделам "
            "(Заказы, Маршруты, Логи и др.) необходимо войти."
        )
        if st.button("Войти", type="primary", key="home_login_btn"):
            st.switch_page("pages/00_Вход.py")
        st.divider()

    # KPI Метрики
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
        c6.metric("Фича флаги", len(metrics.get("feature_flags_disabled", [])))
    else:
        st.warning("Не удалось загрузить метрики. Проверьте подключение к backend.")

    # Здоровье компонентов
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

    st.divider()
    col_refresh, col_interval = st.columns([1, 3])
    with col_refresh:
        if st.button("Обновить", key="home_refresh"):
            clear_api_cache()
            st.rerun()
    with col_interval:
        st.caption("Данные обновляются при нажатии «Обновить» или перезагрузке страницы.")

    st.divider()

    # Onboarding block
    st.header("Что внутри")
    st.markdown(
        """
**Быстрый старт**

- 👋 Если вы здесь впервые — откройте **🎓 Обучение** в боковой панели.
- 🔍 Не знаете, куда идти? Используйте поиск по sidebar (Streamlit native).
- 📚 Все страницы сгруппированы по доменам в sidebar.

**Поддержка**

- Документация по админ-страницам: см. `docs/frontend/`.
- Баги и идеи: внутренний трекер.
"""
    )


# ──────────── Router (st.navigation) ────────────

def _build_pages() -> dict[str, list]:
    """Собрать dict секций для st.navigation().

    Все page-keys валидируются против PAGE_METADATA — если кто-то добавил
    новую страницу, но забыл реестр, она тихо пропускается (как и раньше
    в Quick Access sidebar).
    """
    nav: dict[str, list] = {
        "🏠 Главная": [
            st.Page(_render_home, title="Главная", icon=":material/home:", default=True),
        ],
    }
    for section_name, keys in _SECTIONS.items():
        section_pages: list = []
        for key in keys:
            meta = PAGE_METADATA.get(key)
            if not meta:
                continue
            section_pages.append(
                st.Page(
                    f"pages/{key}.py",
                    title=meta["title"],
                    icon=meta["icon"],
                )
            )
        if section_pages:
            nav[section_name] = section_pages
    return nav


# Run as router
page = st.navigation(_build_pages(), position="sidebar", expanded=0)
page.run()